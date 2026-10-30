#!/usr/bin/env python3
"""Classify replies with Jev, TypeSafe's System One model, through OpenRouter's
Decisions API (POST /api/alpha/decisions). Same OPENROUTER_API_KEY as the LLMs.

Jev makes small judgments; this code makes the decision (truth table in
`decide`). One request per reply: the state is the post + that one reply, and
all questions about it are answered in parallel in the same request.

Usage: python3 jev_classify.py [--model ~typesafe/jev-latest] [--limit N]
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

URL = "https://openrouter.ai/api/alpha/decisions"

# --- All question wording lives here ---------------------------------------
POST = {
    "author": "Grok Imagine (@imagine), xAI's video generation product",
    "text": ("Watch Episode 1 of our Odyssey series made with Grok Imagine. Let us know in "
             "the comments if you'd like a full breakdown of how it was done!"),
    "video": "Episode 1 of 'Odyssey', an AI-generated series episode made with Grok Imagine",
}

QUESTIONS = {
    "on_topic": {
        "type": "noul",
        "instructions": "Does `reply` respond to the Odyssey Episode 1 video or to `post`?",
        "criteria": {
            "true": "The reply reacts to the video, its quality, AI video, or how it was made, "
                    "or only tags people who made it, such as @glumlot_ or @WonderStudiosX.",
            "false": "The reply is spam, self-promotion, or about an unrelated subject, such as "
                     "politics that never mentions the video.",
        },
    },
    "has_opinion": {
        "type": "noul",
        "instructions": "Does `reply` judge the Odyssey Episode 1 video?",
        "criteria": {
            "true": "The commenter praises, criticizes, mocks, or rates the video, "
                    "including through sarcasm.",
            "false": "The commenter only asks a question, asks for the breakdown, tags someone, "
                     "or states a fact, without saying whether the video is good or bad.",
        },
    },
    "opinion": {
        "type": "choice",
        "instructions": "What does the commenter in `reply` think of the Odyssey Episode 1 video?",
        "criteria": {
            "positive": "They like it: impressed, excited, praising the visuals or story.",
            "negative": "They dislike it: call it bad, boring, ugly, or AI slop, or mock it.",
            "mixed": "They both praise and criticize it, for example impressive visuals "
                     "but a weak story, or 'not there yet but improving fast'.",
        },
    },
    "wants_breakdown": {
        "type": "noul",
        "instructions": "Does `reply` ask for the breakdown of how the video was made?",
        "criteria": {
            "true": "The commenter says they want the breakdown or asks how it was made.",
            "false": "The commenter does not ask how the video was made.",
        },
    },
}
YES, NO = 0.7, 0.3


def decide(a):
    """Truth table: Jev's judgments in, one label out. `settled` is False when a
    Noul landed between the thresholds, so the label is a best guess."""
    on_topic, opinionated = a["on_topic"]["noul"], a["has_opinion"]["noul"]
    if on_topic < NO:
        return "off_topic", True
    if opinionated < NO:
        return "neutral", on_topic > YES
    if opinionated > YES:
        return a["opinion"]["choice"], on_topic > YES
    return (a["opinion"]["choice"] if opinionated >= 0.5 else "neutral"), False
# ---------------------------------------------------------------------------


def state_for(c):
    reply = {"author": "@" + c["user"], "text": c["text"]}
    if c["has_media"]:
        reply["attachment"] = "an image or GIF, not shown here"
    return {"post": POST, "reply": reply}


def ask(model, c, key, retries=4):
    body = {"model": model, "state": state_for(c), "questions": QUESTIONS}
    err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                "X-Title": "Jev x-feedback demo"})
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.load(r)
            return resp["answers"], resp.get("usage", {}), resp.get("model")
        except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
            err = e.read().decode()[:300] if isinstance(e, urllib.error.HTTPError) else e
            time.sleep(2 ** attempt)
    # A failed call is an error, never an answer.
    raise RuntimeError(f"reply {c['id']} failed: {err}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="~typesafe/jev-latest")
    ap.add_argument("--input", default="data/replies.jsonl")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    key = os.environ["OPENROUTER_API_KEY"]

    comments = sorted(map(json.loads, open(args.input)), key=lambda c: -c["likes"])
    if args.limit:
        comments = comments[:args.limit]
    out_path = f"data/labels__{args.model.lstrip('~').replace('/', '_')}.jsonl"

    cost = tokens = failed = 0
    served_by = None
    t0 = time.time()
    with open(out_path, "w") as f, ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(ask, args.model, c, key): c for c in comments}
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                answers, usage, served_by = fut.result()
            except RuntimeError as e:
                failed += 1
                print(e, file=sys.stderr)
                continue
            cost += usage.get("cost", 0.0)
            tokens += usage.get("input_tokens", 0)
            label, settled = decide(answers)
            f.write(json.dumps({"id": c["id"], "label": label, "settled": settled,
                                "answers": answers}) + "\n")
    dt = time.time() - t0

    stats = {"model": args.model.lstrip("~"), "served_by": served_by,
             "comments": len(comments) - failed, "failed": failed,
             "seconds": round(dt, 1), "cost_usd": round(cost, 5),
             "prompt_tokens": tokens, "completion_tokens": 0}
    with open(out_path.replace(".jsonl", ".stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
