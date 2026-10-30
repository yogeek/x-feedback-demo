#!/usr/bin/env python3
""""System 1" classification: a small, cheap model maps each comment to ONE
value from a fixed list. No reasoning, no free text, just a constrained choice.

Comments are batched (N per request) so the instructions are paid once per
batch, and the answer is forced through a JSON schema whose `label` is an enum,
so the model cannot answer outside the list.

Usage:
  python3 classify.py --model mistralai/mistral-nemo
  python3 classify.py --model anthropic/claude-sonnet-5.5 --limit 300   # reference
Needs OPENROUTER_API_KEY in the environment.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

URL = "https://openrouter.ai/api/v1/chat/completions"
# Models whose endpoints cannot turn reasoning off.
MUST_REASON = ("gpt-oss", "claude-sonnet-5.5")

QUESTION = ("What is the commenter's opinion of Episode 1 of the 'Odyssey' series, "
            "an AI-generated video made with Grok Imagine?")
LABELS = {
    "positive": "likes it, impressed, praise, excited for more",
    "negative": "dislikes it, mocks it, calls it slop/bad/boring, criticizes AI video quality",
    "mixed": "both praise and criticism (e.g. 'impressive tech but bad story')",
    "neutral": "no opinion: questions, requests for the breakdown, tags, factual remarks",
    "off_topic": "unrelated, spam, promotion, or politics with no link to the video",
}

SYSTEM = f"""You label X (Twitter) replies to a post by @imagine announcing Episode 1 of "Odyssey", a video made with Grok Imagine.
Question: {QUESTION}
Pick exactly one label per reply:
""" + "\n".join(f"- {k}: {v}" for k, v in LABELS.items()) + """
Sarcasm counts as what it really means. "[media]" means the reply also has an image/GIF you cannot see; judge from the text.
Return one entry per reply, using the reply's index."""


def schema(n):
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "labels",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"labels": {
                    "type": "array", "minItems": n, "maxItems": n,
                    "items": {"type": "object", "properties": {
                        "i": {"type": "integer"},
                        "label": {"type": "string", "enum": list(LABELS)},
                    }, "required": ["i", "label"], "additionalProperties": False},
                }},
                "required": ["labels"], "additionalProperties": False,
            },
        },
    }


def call(model, batch, key, retries=4):
    lines = []
    for i, c in enumerate(batch):
        text = c["text"][:500].replace("\n", " ") or "(no text)"
        lines.append(f"{i}. {text}{' [media]' if c['has_media'] else ''}")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": "\n".join(lines)}],
        "max_tokens": 30 * len(batch) + 50,
        "response_format": schema(len(batch)),
        "provider": {"require_parameters": True},
        "usage": {"include": True},
    }
    if "claude" not in model:  # Claude endpoints reject temperature with require_parameters
        body["temperature"] = 0
    if any(t in model for t in MUST_REASON):
        body["reasoning"] = {"effort": "low"}
        body["max_tokens"] += 2000
    elif any(t in model for t in ("claude", "gemini", "gpt-5", "gpt-6")):
        body["reasoning"] = {"enabled": False}
    err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                "X-Title": "Jev x-feedback demo"})
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.load(r)
            out = json.loads(resp["choices"][0]["message"]["content"])["labels"]
            by_i = {o["i"]: o["label"] for o in out if o["label"] in LABELS}
            if len(by_i) != len(batch):
                raise ValueError(f"got {len(by_i)} labels for {len(batch)} replies")
            u = resp.get("usage", {})
            return by_i, u.get("cost", 0.0), u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        except (urllib.error.URLError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            err = e.read().decode()[:300] if isinstance(e, urllib.error.HTTPError) else e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"batch failed: {err}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--input", default="data/replies.jsonl")
    ap.add_argument("--limit", type=int, help="only the N most-liked replies")
    ap.add_argument("--batch-size", type=int, default=20)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    key = os.environ["OPENROUTER_API_KEY"]

    comments = [json.loads(l) for l in open(args.input)]
    comments.sort(key=lambda c: -c["likes"])
    if args.limit:
        comments = comments[:args.limit]
    out_path = f"data/labels__{args.model.replace('/', '_')}.jsonl"
    batches = [comments[i:i + args.batch_size] for i in range(0, len(comments), args.batch_size)]

    cost = ptok = ctok = failed = 0
    t0 = time.time()
    with open(out_path, "w") as f, ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(call, args.model, b, key): b for b in batches}
        for fut in as_completed(futures):
            b = futures[fut]
            try:
                by_i, c, p, q = fut.result()
            except RuntimeError as e:
                failed += len(b)
                print(e, file=sys.stderr)
                continue
            cost, ptok, ctok = cost + c, ptok + p, ctok + q
            for i, com in enumerate(b):
                f.write(json.dumps({"id": com["id"], "label": by_i[i]}) + "\n")
    dt = time.time() - t0

    stats = {"model": args.model, "comments": len(comments) - failed, "failed": failed,
             "seconds": round(dt, 1), "cost_usd": round(cost, 5),
             "prompt_tokens": ptok, "completion_tokens": ctok}
    with open(out_path.replace(".jsonl", ".stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
