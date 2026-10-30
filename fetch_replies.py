#!/usr/bin/env python3
"""Fetch replies of an X post for free via the public FxTwitter API.

No X account, no paid X API: api.fxtwitter.com/2/conversation/<id> returns
~35 replies per page plus a cursor for the next page.

Usage: python3 fetch_replies.py <post_url_or_id> [--max-pages N] [--out FILE]
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.fxtwitter.com/2/conversation/{id}"
UA = "x-feedback-demo/1.0"


def get_page(post_id, cursor=None, retries=4):
    url = API.format(id=post_id)
    if cursor:
        url += "?" + urllib.parse.urlencode({"cursor": cursor})
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            wait = 2 ** (attempt + 1)
            print(f"  page error ({e}), retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("post")
    ap.add_argument("--max-pages", type=int, default=200)
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between pages")
    ap.add_argument("--out", default="data/replies.jsonl")
    args = ap.parse_args()

    post_id = re.search(r"(\d{10,})", args.post).group(1)
    seen, cursor, kept = set(), None, 0
    with open(args.out, "w") as f:
        for page in range(1, args.max_pages + 1):
            data = get_page(post_id, cursor)
            if not data:
                print("giving up on this page", file=sys.stderr)
                break
            if page == 1:
                s = data["status"]
                print(f"Post: {s['text'][:80]!r}  replies={s['replies']} views={s['views']}")
            new = 0
            for r in data.get("replies", []):
                if r["id"] in seen:
                    continue
                seen.add(r["id"])
                new += 1
                # Strip the leading "@imagine @WonderStudiosX ..." mention block.
                text = re.sub(r"^(@\w+\s+)+", "", r.get("text", "")).strip()
                f.write(json.dumps({
                    "id": r["id"],
                    "user": r["author"]["screen_name"],
                    "followers": r["author"].get("followers"),
                    "text": text,
                    "likes": r.get("likes", 0),
                    "replies": r.get("replies", 0),
                    "lang": r.get("lang"),
                    "has_media": bool(r.get("media")),
                    "created_at": r.get("created_at"),
                    "direct": (r.get("replying_to") or {}).get("status") == post_id,
                }, ensure_ascii=False) + "\n")
            kept += new
            cursor = (data.get("cursor") or {}).get("bottom")
            print(f"page {page}: +{new} (total {kept})")
            if not cursor or new == 0:
                break
            time.sleep(args.delay)
    print(f"Saved {kept} replies to {args.out}")


if __name__ == "__main__":
    main()
