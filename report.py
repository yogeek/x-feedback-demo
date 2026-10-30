#!/usr/bin/env python3
"""Build REPORT.md: label distribution per model, cost/speed, and agreement of
each fast model with the reference model on the replies both labeled.

Usage: python3 report.py --reference anthropic/claude-sonnet-5.5
"""
import argparse
import glob
import json
from collections import Counter

from classify import LABELS, QUESTION


def load(path):
    return {r["id"]: r["label"] for r in map(json.loads, open(path))}


def load_raw(path):
    return {r["id"]: r for r in map(json.loads, open(path))}


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in LABELS) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def bar(p, width=30):
    return "#" * round(p * width)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True)
    ap.add_argument("--main", default="typesafe/jev-latest", help="model whose answer is reported")
    ap.add_argument("--out", default="REPORT.md")
    args = ap.parse_args()

    comments = {c["id"]: c for c in map(json.loads, open("data/replies.jsonl"))}
    runs = {}
    for path in sorted(glob.glob("data/labels__*.jsonl")):
        stats = json.load(open(path.replace(".jsonl", ".stats.json")))
        runs[stats["model"]] = (load(path), stats)
    ref_labels = runs[args.reference][0]
    main_model = args.main

    L = [f"# X feedback: {QUESTION}", ""]
    L.append(f"Source: {len(comments)} replies fetched for free via the FxTwitter public API.")
    L.append("")

    # 1. The answer, from the cheapest fast model over all replies.
    labels, stats = runs[main_model]
    cnt = Counter(labels.values())
    likes = Counter()
    for cid, lab in labels.items():
        likes[lab] += comments[cid]["likes"] + 1
    n, total_likes = sum(cnt.values()), sum(likes.values())
    opinion = {k: cnt[k] for k in ("positive", "negative", "mixed")}
    L += [f"## Answer ({main_model}, {n} replies)", "",
          "| label | replies | % | % weighted by likes | |", "|---|---:|---:|---:|---|"]
    for k in LABELS:
        L.append(f"| {k} | {cnt[k]} | {cnt[k]/n:.0%} | {likes[k]/total_likes:.0%} | `{bar(cnt[k]/n)}` |")
    op_n = sum(opinion.values()) or 1
    L += ["", f"Among replies that express an opinion ({op_n}): "
          + ", ".join(f"{k} {v/op_n:.0%}" for k, v in opinion.items()), ""]

    # 2. Cost and speed of each run.
    L += ["## Cost and speed", "",
          "| model | labeled | failed | time (s) | cost (USD) | USD per 1M replies | agreement with reference | Cohen's kappa |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for m, (lab, st) in sorted(runs.items(), key=lambda kv: kv[1][1]["cost_usd"] / max(kv[1][1]["comments"], 1)):
        per_m = st["cost_usd"] / max(st["comments"], 1) * 1e6
        shared = [cid for cid in lab if cid in ref_labels]
        if m == args.reference:
            agree = kap = "(reference)"
        elif shared:
            a = [lab[c] for c in shared]
            b = [ref_labels[c] for c in shared]
            agree = f"{sum(x == y for x, y in zip(a, b))/len(shared):.0%} (n={len(shared)})"
            kap = f"{kappa(a, b):.2f}"
        else:
            agree = kap = "n/a"
        L.append(f"| {m} | {st['comments']} | {st['failed']} | {st['seconds']} | {st['cost_usd']:.4f} | {per_m:,.0f} | {agree} | {kap} |")
    L.append("")

    # Jev extras: settled share and the speculative breakdown question.
    jev_path = f"data/labels__{main_model.replace('/', '_')}.jsonl"
    raw = load_raw(jev_path)
    if raw and "settled" in next(iter(raw.values())):
        settled = [c for c, r in raw.items() if r["settled"] and c in ref_labels]
        agree = sum(raw[c]["label"] == ref_labels[c] for c in settled) / max(len(settled), 1)
        unsettled = sum(not r["settled"] for r in raw.values())
        brk = [c for c, r in raw.items() if r["answers"]["wants_breakdown"]["noul"] > 0.7]
        L += [f"## {main_model} details", "",
              f"- Settled answers (every Noul outside 0.3-0.7): {len(raw) - unsettled}/{len(raw)}. "
              f"Agreement with reference on settled answers: {agree:.0%} (n={len(settled)}). "
              f"The {unsettled} unsettled replies can go to a stronger model or a person.",
              f"- Replies asking for the breakdown (`wants_breakdown` > 0.7): {len(brk)}, "
              f"totaling {sum(comments[c]['likes'] for c in brk)} likes.", ""]

    # 3. Confusion matrix main fast model vs reference.
    shared = [cid for cid in labels if cid in ref_labels]
    if shared:
        L += [f"## Where {main_model} disagrees with {args.reference}", "",
              "Rows: reference label. Columns: fast model label.", "",
              "| ref \\ fast | " + " | ".join(LABELS) + " |", "|---" * (len(LABELS) + 1) + "|"]
        conf = Counter((ref_labels[c], labels[c]) for c in shared)
        for r in LABELS:
            L.append(f"| {r} | " + " | ".join(str(conf[(r, f)]) for f in LABELS) + " |")
        L += ["", "Sample disagreements (most liked first):", ""]
        dis = sorted((c for c in shared if labels[c] != ref_labels[c]), key=lambda c: -comments[c]["likes"])
        for c in dis[:10]:
            t = comments[c]["text"][:140].replace("\n", " ").replace("|", "/")
            L.append(f"- ref=`{ref_labels[c]}` fast=`{labels[c]}` ({comments[c]['likes']} likes): {t}")
        L.append("")

    # 4. Examples per label.
    L += ["## Most liked replies per label", ""]
    for k in LABELS:
        top = sorted((c for c, lab in labels.items() if lab == k), key=lambda c: -comments[c]["likes"])[:3]
        L.append(f"**{k}**")
        for c in top:
            t = comments[c]["text"][:160].replace("\n", " ")
            L.append(f"- ({comments[c]['likes']} likes) {t}")
        L.append("")

    open(args.out, "w").write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
