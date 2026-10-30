#!/usr/bin/env python3
"""Label every reply with the reference model once, for all questions.
The race UI measures each model's agreement against data/reference.json.

Usage: python3 build_reference.py [--model anthropic/claude-sonnet-5.5]
"""
import argparse
import json
import os
import time

from engine import run_model
from questions import QUESTIONS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="anthropic/claude-sonnet-5.5")
    args = ap.parse_args()
    comments = [json.loads(l) for l in open("data/replies.jsonl")]
    qids = list(QUESTIONS)
    res = run_model(args.model, "llm", qids, comments, os.environ["OPENROUTER_API_KEY"],
                    on_progress=lambda p: print(f"\r{p['done']}/{p['total']}", end="", flush=True))
    print()
    labels = {q: {cid: a[q]["label"] for cid, a in res["items"].items()} for q in qids}
    json.dump({"model": args.model, "created": time.strftime("%Y-%m-%d %H:%M"),
               "cost_usd": res["cost"], "seconds": res["seconds"], "failed": res["failed"],
               "labels": labels}, open("data/reference.json", "w"), indent=1)
    print(f"{len(res['items'])} labeled, {len(res['failed'])} failed, "
          f"${res['cost']:.4f}, {res['seconds']:.0f}s, errors: {res['errors']}")


if __name__ == "__main__":
    main()
