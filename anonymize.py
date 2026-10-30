#!/usr/bin/env python3
"""Pseudonymize the fetched replies before publishing the data.

Replaces every reply id with r0001..., every author handle with user-001..., and, inside
reply texts, the @mentions of private accounts and the links to other posts, in data/ and
results/. Accounts of the people and companies behind the post (PUBLIC_ACCOUNTS) keep
their handle.
Run it after fetch_replies.py and before committing. Running it twice is harmless.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent
PUBLIC_ACCOUNTS = {"imagine", "grok", "elonmusk", "techcrunch", "apple", "wonderstudiosx",
                   "gossip_goblin", "glumlot_"}
MENTION = re.compile(r"@(\w+)")
POST_LINK = re.compile(r"https?://(?:x|twitter)\.com/\w+/status/\S+")


def build_maps():
    ids, users = {}, {}
    for line in open(ROOT / "data/replies.jsonl"):
        c = json.loads(line)
        if not c["id"].startswith("r"):
            ids[c["id"]] = f"r{len(ids) + 1:04d}"
        u = c["user"]
        if u.lower() not in PUBLIC_ACCOUNTS and not u.startswith("user-") and u not in users:
            users[u] = f"user-{len(users) + 1:03d}"
    return ids, users


def rewrite(obj, ids, users, key=None):
    if isinstance(obj, dict):
        return {ids.get(k, k): rewrite(v, ids, users, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rewrite(v, ids, users) for v in obj]
    if isinstance(obj, str):
        if key == "user":
            return users.get(obj, obj)
        if key == "text":
            obj = POST_LINK.sub("[link to a post]", obj)
            return MENTION.sub(lambda m: m[0] if m[1].lower() in PUBLIC_ACCOUNTS
                               else "@" + users.get(m[1], "user"), obj)
        return ids.get(obj, obj)
    return obj


def main():
    ids, users = build_maps()
    for path in sorted([*ROOT.glob("data/*.json*"), *ROOT.glob("results/*.json")]):
        if path.suffix == ".jsonl":
            rows = [rewrite(json.loads(l), ids, users) for l in open(path) if l.strip()]
            path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        else:
            data = rewrite(json.load(open(path)), ids, users)
            path.write_text(json.dumps(data, indent=1 if path.name == "reference.json" else None))
    print(f"{len(ids)} reply ids and {len(users)} handles replaced")


if __name__ == "__main__":
    main()
