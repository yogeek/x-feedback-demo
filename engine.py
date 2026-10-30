"""Run one model over a set of replies and questions, reporting progress.

Decision models: one request per reply to OpenRouter's Decisions API. The state
is the post + the reply; the sub-questions of every selected question go in the
same request, so the state is read and paid for once.

LLMs: chat completions with a JSON schema whose fields are enums of the labels,
`batch` replies per call. A call whose output does not parse is a failure; its
replies get no answer.
"""
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from questions import CONTEXT, POST, QUESTIONS, decide

BASE = "https://openrouter.ai/api"
MUST_REASON = ("gpt-oss", "claude-sonnet-5.5")  # endpoints that cannot turn reasoning off
SEP = "__"


def _post(path, body, key, timeout=120):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "X-Title": "Jev reply race"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _err(e):
    if isinstance(e, urllib.error.HTTPError):
        try:
            return f"HTTP {e.code}: {e.read().decode()[:200]}"
        except Exception:
            return f"HTTP {e.code}"
    return f"{type(e).__name__}: {e}"


# --- decision models --------------------------------------------------------

def _state(c):
    reply = {"author": "@" + c["user"], "text": c["text"]}
    if c["has_media"]:
        reply["attachment"] = "an image or GIF, not shown here"
    return {"post": POST, "reply": reply}


def _decision_call(model, qids, c, key, retries=3):
    questions = {f"{q}{SEP}{k}": v for q in qids for k, v in QUESTIONS[q]["decision"].items()}
    body = {"model": model, "state": _state(c), "questions": questions}
    err = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            resp = _post("/alpha/decisions", body, key, timeout=60)
            lat = time.time() - t0
            raw = resp["answers"]
            out = {}
            for q in qids:
                sub = {k.split(SEP, 1)[1]: v for k, v in raw.items() if k.startswith(q + SEP)}
                label, settled, dist = decide(q, sub)
                out[q] = {"label": label, "settled": settled, "dist": dist}
            u = resp.get("usage", {})
            return {"items": {c["id"]: out}, "raw": {c["id"]: raw}, "latency": lat,
                    "cost": u.get("cost", 0.0), "in": u.get("input_tokens", 0),
                    "out": u.get("output_tokens", 0), "served_by": resp.get("model"), "n": 1}
        except (urllib.error.URLError, KeyError, TypeError, ValueError, TimeoutError) as e:
            err = _err(e)
            time.sleep(1.5 * (attempt + 1))
    return {"items": {}, "failed": [c["id"]], "error": err, "n": 1, "cost": 0.0}


# --- LLMs -------------------------------------------------------------------

def _system(qids):
    lines = [f"You label {CONTEXT}", "Answer every question below for every reply, choosing "
             "exactly one label per question.", ""]
    for q in qids:
        lines.append(f"Question `{q}`: {QUESTIONS[q]['title']}")
        lines += [f"- {k}: {v}" for k, v in QUESTIONS[q]["labels"].items()]
        lines.append("")
    lines.append("Sarcasm counts as what it really means. \"[media]\" means the reply also has an "
                 "image/GIF you cannot see. Return one entry per reply, using the reply's index.")
    return "\n".join(lines)


def _schema(qids, n):
    props = {"i": {"type": "integer"}}
    props.update({q: {"type": "string", "enum": list(QUESTIONS[q]["labels"])} for q in qids})
    return {"type": "json_schema", "json_schema": {"name": "labels", "strict": True, "schema": {
        "type": "object", "required": ["labels"], "additionalProperties": False,
        "properties": {"labels": {"type": "array", "minItems": n, "maxItems": n, "items": {
            "type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}}}}}}


def _llm_call(model, qids, batch, key, retries=3):
    lines = [f"{i}. {c['text'][:500].replace(chr(10), ' ') or '(no text)'}"
             f"{' [media]' if c['has_media'] else ''}" for i, c in enumerate(batch)]
    body = {"model": model,
            "messages": [{"role": "system", "content": _system(qids)},
                         {"role": "user", "content": "\n".join(lines)}],
            "max_tokens": (15 + 12 * len(qids)) * len(batch) + 60,
            "response_format": _schema(qids, len(batch)),
            "provider": {"require_parameters": True}, "usage": {"include": True}}
    if "claude" not in model:  # Claude endpoints reject temperature with require_parameters
        body["temperature"] = 0
    if any(t in model for t in MUST_REASON):
        body["reasoning"] = {"effort": "low"}
        body["max_tokens"] += 2000
    elif any(t in model for t in ("claude", "gemini", "gpt-5", "gpt-6")):
        body["reasoning"] = {"enabled": False}
    err, spent = None, 0.0
    for attempt in range(retries):
        t0 = time.time()
        try:
            resp = _post("/v1/chat/completions", body, key)
            lat = time.time() - t0
            spent += (resp.get("usage") or {}).get("cost", 0.0)  # failed parses are still billed
            content = resp["choices"][0]["message"]["content"]
            rows = json.loads(content)["labels"]
            by_i = {r["i"]: r for r in rows}
            if sorted(by_i) != list(range(len(batch))):
                raise ValueError(f"answered {len(by_i)} of {len(batch)} replies")
            items, raw = {}, {}
            for i, c in enumerate(batch):
                r = by_i[i]
                if any(r.get(q) not in QUESTIONS[q]["labels"] for q in qids):
                    raise ValueError("label outside the list")
                items[c["id"]] = {q: {"label": r[q]} for q in qids}
                raw[c["id"]] = json.dumps(r)
            u = resp.get("usage", {})
            return {"items": items, "raw": raw, "latency": lat, "cost": spent,
                    "in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0),
                    "served_by": resp.get("model"), "n": len(batch)}
        except (urllib.error.URLError, KeyError, TypeError, ValueError, IndexError, TimeoutError) as e:
            err = _err(e)
            time.sleep(1.5 * (attempt + 1))
    return {"items": {}, "failed": [c["id"] for c in batch], "error": err,
            "n": len(batch), "cost": spent}


# --- runner -----------------------------------------------------------------

def run_model(model, kind, qids, comments, key, on_progress=None, llm_batch=20,
              workers=None, stop=None):
    """Label `comments` with `model`. Calls on_progress(snapshot) after each call."""
    if kind == "decision":
        units = [[c] for c in comments]
        call = lambda u: _decision_call(model, qids, u[0], key)
        workers = workers or 32
    else:
        units = [comments[i:i + llm_batch] for i in range(0, len(comments), llm_batch)]
        call = lambda u: _llm_call(model, qids, u, key)
        workers = workers or (32 if llm_batch == 1 else 8)

    res = {"items": {}, "raw": {}, "failed": [], "errors": [], "latencies": [],
           "cost": 0.0, "in": 0, "out": 0, "served_by": None, "calls": len(units)}
    done, t0 = 0, time.time()
    pool = ThreadPoolExecutor(workers)
    pending = {pool.submit(call, u) for u in units}
    while pending:
        # Short timeout so a stop request is honored without waiting for slow calls.
        finished, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
        for fut in finished:
            r = fut.result()
            done += r["n"]
            res["cost"] += r.get("cost", 0.0)
            res["items"].update(r["items"])
            res["raw"].update(r.get("raw", {}))
            res["failed"] += r.get("failed", [])
            if r.get("error"):
                res["errors"].append(r["error"])
            if "latency" in r:
                res["latencies"].append(r["latency"])
                res["in"] += r["in"]
                res["out"] += r["out"]
                res["served_by"] = res["served_by"] or r["served_by"]
            if on_progress:
                on_progress({"done": done, "total": len(comments), "failed": len(res["failed"]),
                             "cost": res["cost"], "tokens_out": res["out"],
                             "elapsed": time.time() - t0})
        if stop and stop.is_set() and pending:
            res["stopped"] = True
            break
    pool.shutdown(wait=False, cancel_futures=True)  # calls in flight finish unseen
    res["processed"] = done
    res["seconds"] = time.time() - t0
    lat = res["latencies"]
    res["latency_p50"] = statistics.median(lat) if lat else None
    res["errors"] = res["errors"][:5]
    return res
