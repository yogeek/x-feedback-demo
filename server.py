#!/usr/bin/env python3
"""Reply race: local web UI comparing decision models and LLMs.

The OpenRouter key stays in this process; the browser only talks to it.
Progress streams to the page with Server-Sent Events.

Usage:
  eval "$(pass show env/openrouter)"
  python3 server.py            # then open http://127.0.0.1:8765
"""
import argparse
import json
import mimetypes
import os
import threading
import time
import urllib.request
import uuid
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from engine import run_model
from questions import QUESTIONS, public_catalog

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
KEY = os.environ.get("OPENROUTER_API_KEY", "")

MODELS = [
    # id, display name, kind, note
    ("typesafe/jev-1.14", "Jev 1.14", "decision", "TypeSafe, the first System One model"),
    ("liquid/d1", "Liquid d1", "decision", "Liquid AI decision model"),
    ("perplexity/pplx-decider-flash-v1.2", "Perplexity Decider Flash", "decision", "Perplexity"),
    ("openai/gpt-6-luna-decisions", "GPT-6 Luna Decisions", "decision", "OpenAI"),
    ("microsoft/microsoft-decision-1", "Microsoft Decision 1", "decision", "Microsoft"),
    ("cloudflare/clef-flash", "Cloudflare Clef Flash", "decision", "Cloudflare"),
    ("mistralai/mistral-nemo", "Mistral Nemo", "llm", "12B, one of the cheapest LLMs"),
    ("meta-llama/llama-3.1-8b-instruct", "Llama 3.1 8B", "llm", "8B, often breaks the JSON format"),
    ("google/gemma-3-12b-it", "Gemma 3 12B", "llm", "12B open model"),
    ("openai/gpt-oss-20b", "gpt-oss-20b", "llm", "small reasoning LLM"),
    ("anthropic/claude-haiku-5.5", "Claude Haiku 5.5", "llm", "fast frontier LLM"),
    ("anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5", "llm", "frontier LLM, reasoning on"),
]
MODEL_BY_ID = {m[0]: m for m in MODELS}
SAMPLES = [25, 50, 100, 250, 581]

COMMENTS = sorted((json.loads(l) for l in open(ROOT / "data/replies.jsonl")),
                  key=lambda c: -c["likes"])
REF_PATH = ROOT / "data/reference.json"


def load_reference():
    return json.load(open(REF_PATH)) if REF_PATH.exists() else None


def fetch_prices():
    prices = {}
    for url in ("https://openrouter.ai/api/v1/models",
                "https://openrouter.ai/api/v1/models?output_modalities=decisions"):
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}"})
            with urllib.request.urlopen(req, timeout=20) as r:
                for m in json.load(r)["data"]:
                    p = m.get("pricing", {})
                    prices[m["id"]] = {"in": float(p.get("prompt", 0)) * 1e6,
                                       "out": float(p.get("completion", 0)) * 1e6}
        except Exception as e:  # the UI still works without prices
            print("price fetch failed:", e)
    return prices


PRICES = {}


# --- metrics ----------------------------------------------------------------

def kappa(a, b, labels):
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in labels) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def metrics(res, qids, comments, ref):
    # A stopped model is scored only on the replies it got through.
    stopped = res.get("stopped", False)
    done = {cid for cid in res["items"]} | set(res["failed"])
    if stopped:
        comments = [c for c in comments if c["id"] in done]
    n = max(len(comments), 1)
    m = {"stopped": stopped, "processed": res.get("processed", n), "seconds": res["seconds"],
         "cost": res["cost"], "cost_per_1m": res["cost"] / n * 1e6,
         "tokens_in": res["in"], "tokens_out": res["out"], "calls": res["calls"],
         "latency_p50": res["latency_p50"], "answered": len(res["items"]),
         "failed": len(res["failed"]), "errors": res["errors"], "served_by": res["served_by"],
         "per_question": {}}
    agrees = []
    for q in qids:
        labels = list(QUESTIONS[q]["labels"])
        counts = Counter(a[q]["label"] for a in res["items"].values())
        pq = {"counts": {k: counts[k] for k in labels}}
        settled = [a[q]["settled"] for a in res["items"].values() if "settled" in a[q]]
        if settled:
            pq["settled"] = sum(settled) / len(settled)
        if ref:
            rl = ref["labels"][q]
            with_ref = [c["id"] for c in comments if c["id"] in rl]
            hits = sum(1 for cid in with_ref
                       if cid in res["items"] and res["items"][cid][q]["label"] == rl[cid])
            both = [cid for cid in with_ref if cid in res["items"]]
            pq["agreement"] = hits / len(with_ref) if with_ref else None
            pq["kappa"] = kappa([res["items"][c][q]["label"] for c in both],
                                [rl[c] for c in both], labels)
            if "yes" in labels:  # rare "yes" answers: how many did the model find?
                wanted = [cid for cid in with_ref if rl[cid] == "yes"]
                pq["to_find"] = len(wanted)
                pq["found"] = sum(1 for cid in wanted
                                  if cid in res["items"] and res["items"][cid][q]["label"] == "yes")
            if pq["agreement"] is not None:
                agrees.append(pq["agreement"])
        m["per_question"][q] = pq
    m["agreement"] = sum(agrees) / len(agrees) if agrees else None
    return m


# --- races ------------------------------------------------------------------

class Race:
    def __init__(self, qids, model_ids, sample, llm_batch):
        self.id = uuid.uuid4().hex[:10]
        self.qids, self.model_ids = qids, model_ids
        self.comments = COMMENTS[:sample]
        self.llm_batch = llm_batch
        self.events, self.cond = [], threading.Condition()
        self.stop = threading.Event()
        self.results, self.finish_order = {}, []
        self.ref = load_reference()
        self.t0 = time.time()
        self.done = False

    def emit(self, ev):
        with self.cond:
            ev["t"] = round(time.time() - self.t0, 3)
            self.events.append(ev)
            self.cond.notify_all()

    def start(self):
        self.emit({"type": "start", "models": self.model_ids, "total": len(self.comments),
                   "questions": self.qids, "llm_batch": self.llm_batch})
        threads = [threading.Thread(target=self._run, args=(m,), daemon=True) for m in self.model_ids]
        for t in threads:
            t.start()
        threading.Thread(target=self._finish, args=(threads,), daemon=True).start()

    def _run(self, mid):
        kind = MODEL_BY_ID[mid][2]
        try:
            res = run_model(mid, kind, self.qids, self.comments, KEY, llm_batch=self.llm_batch,
                            stop=self.stop,
                            on_progress=lambda p: self.emit({"type": "progress", "model": mid, **p}))
        except Exception as e:
            self.emit({"type": "error", "model": mid, "error": str(e)})
            return
        with self.cond:
            self.finish_order.append(mid)
            place = len(self.finish_order)
        self.results[mid] = res
        self.emit({"type": "finish", "model": mid, "place": place,
                   "metrics": metrics(res, self.qids, self.comments, self.ref)})

    def _finish(self, threads):
        for t in threads:
            t.join()
        payload = self.summary()
        out = ROOT / "results"
        out.mkdir(exist_ok=True)
        json.dump(payload, open(out / f"race-{time.strftime('%Y%m%d-%H%M%S')}-{self.id}.json", "w"))
        self.done = True
        self.emit({"type": "done", "summary": payload})

    def summary(self):
        ref = self.ref
        items = []
        for c in self.comments:
            row = {"id": c["id"], "user": c["user"], "text": c["text"], "likes": c["likes"],
                   "has_media": c["has_media"], "answers": {},
                   "reference": {q: ref["labels"][q].get(c["id"]) for q in self.qids} if ref else None}
            for mid, res in self.results.items():
                a = res["items"].get(c["id"])
                row["answers"][mid] = {"q": a, "raw": res["raw"].get(c["id"])} if a else None
            items.append(row)
        return {"id": self.id, "questions": self.qids, "models": self.model_ids,
                "sample": len(self.comments), "llm_batch": self.llm_batch,
                "reference_model": ref["model"] if ref else None,
                "finish_order": self.finish_order,
                "metrics": {mid: metrics(r, self.qids, self.comments, ref)
                            for mid, r in self.results.items()},
                "items": items}


RACES = {}


# --- HTTP -------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/config":
            ref = load_reference()
            return self._json({
                "questions": public_catalog(),
                "models": [{"id": i, "name": n, "kind": k, "note": note,
                            "price": PRICES.get(i)} for i, n, k, note in MODELS],
                "samples": SAMPLES, "total_comments": len(COMMENTS),
                "post": {"url": "https://x.com/imagine/status/2113712964419063911",
                         "author": "@imagine", "title": "Odyssey, Episode 1"},
                "reference": {"model": ref["model"], "name": MODEL_BY_ID[ref["model"]][1],
                              "created": ref["created"]} if ref else None,
                "has_key": bool(KEY)})
        if path == "/api/race/current":
            running = [r for r in RACES.values() if not r.done]
            return self._json({"id": running[0].id if running else None})
        if path.startswith("/api/race/") and path.endswith("/events"):
            race = RACES.get(path.split("/")[3])
            if not race:
                return self._json({"error": "Race not found. Start a new race."}, 404)
            return self._stream(race)
        if path == "/":
            path = "/index.html"
        f = (STATIC / path.lstrip("/")).resolve()
        if STATIC.resolve() in f.parents and f.is_file():
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        self._json({"error": "not found"}, 404)

    def _stream(self, race):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        i = 0
        try:
            while True:
                with race.cond:
                    while i >= len(race.events):
                        race.cond.wait(timeout=15)
                        if i >= len(race.events):
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                    batch = race.events[i:]
                    i = len(race.events)
                for ev in batch:
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                self.wfile.flush()
                if any(ev["type"] == "done" for ev in batch):
                    return
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/race":
            if not KEY:
                return self._json({"error": "OPENROUTER_API_KEY is not set in the server's "
                                            "environment. Restart the server after exporting it."}, 400)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            qids = [q for q in body.get("questions", []) if q in QUESTIONS]
            mids = [m for m in body.get("models", []) if m in MODEL_BY_ID]
            if not qids or not mids:
                return self._json({"error": "Pick at least one question and one model."}, 400)
            sample = min(int(body.get("sample", 100)), len(COMMENTS))
            batch = 1 if int(body.get("llm_batch", 20)) == 1 else 20
            running = [r for r in RACES.values() if not r.done]
            if running:
                return self._json({"error": "A race is already running. Stop it or wait for the end.",
                                   "running": running[0].id}, 409)
            race = Race(qids, mids, sample, batch)
            RACES[race.id] = race
            race.start()
            return self._json({"id": race.id})
        if path.startswith("/api/race/") and path.endswith("/stop"):
            race = RACES.get(path.split("/")[3])
            if race:
                race.stop.set()
            return self._json({"ok": bool(race)})
        self._json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    PRICES.update(fetch_prices())
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print(f"Reply race on http://{args.host}:{args.port}  (key loaded: {bool(KEY)})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
