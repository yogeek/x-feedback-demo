# AGENTS.md

Guide for coding agents working on this repository. Read `README.md` first for what the
demo does.

## Layout

- `server.py`: HTTP server (stdlib `ThreadingHTTPServer`), model list `MODELS`, sample
  sizes `SAMPLES`, the `Race` class, `metrics()`, saved races in `results/`.
- `engine.py`: `run_model()` calls one model on a list of replies and reports progress
  through a callback. Supports a `stop` event; stopped models are scored only on the
  replies they processed.
- `questions.py`: every user-facing question. Each entry has the LLM labels, the decision
  sub-questions (Noul / Choice / Score) and a `combine` function. `decide()` turns the
  decision answers into one label. All question wording lives here.
- `static/index.html`, `static/style.css`, `static/app.js`: the page, vanilla JS, no build step.
- `static/intro.html` (English), `static/intro-fr.html` (French), `static/deck.css`,
  `static/deck.js`: the introduction slides. Change both languages together. Every
  figure on them comes from a vendor's documentation or from a saved race in `results/`; keep
  it that way, and label illustrative examples as such.
- `data/replies.jsonl`: the pseudonymized replies. `data/reference.json`: the answer key.
- `classify.py`, `jev_classify.py`, `report.py`: the first CLI version, kept as is.

## Rules

- **Python standard library only**, no `pip install`. Frontend: no framework, no bundler.
- **The OpenRouter key stays server side.** Read it from `OPENROUTER_API_KEY`; never send
  it to the browser, write it to a file, or print it. Locally it comes from `pass`:
  `eval "$(pass show env/openrouter)" && python3 server.py`, in one shell command.
- **Every race and every reference build costs real money.** Do not start races or rerun
  `build_reference.py` (~$0.35) to test something a 25-reply race can show. One race at a
  time is enforced by the server (HTTP 409).
- **Data must stay pseudonymized.** After `fetch_replies.py`, run `anonymize.py` before
  committing. Never commit raw handles, tweet ids, or links to other users' posts.
- Adding a question: add it to `QUESTIONS` in `questions.py`, then rerun
  `build_reference.py` so the answer key covers it.
- Adding a model: add a row to `MODELS` in `server.py` (`"decision"` or `"llm"`). LLMs that
  cannot turn reasoning off or reject `temperature` need the special cases in `engine.py`.
- Decision models follow the TypeSafe practice: split the decision into small typed
  judgments, combine them in code, treat a Noul between 0.3 and 0.7 as "not sure".

## Writing

- The page targets a non-technical audience: plain words ("right answers", "cost for 1M
  replies"), technical metrics only under "Technical details".
- No em dashes in code, comments, copy or docs. No decorative sentences.
- Colors: decision models blue `#2a78d6`, LLMs orange `#eb6834`; labels use the other
  palette slots in fixed order; the answer key is drawn as a ring, not a color.

## Run and check

```bash
eval "$(pass show env/openrouter)" && python3 server.py   # http://127.0.0.1:8765
kill $(lsof -t -iTCP:8765 -sTCP:LISTEN)                   # stop it (not pkill -f)
```

There are no automated tests. Check a change by running a 25-reply race in the browser
and going through the whole flow: setup, start, live lanes, stop, results, a second race,
and a reload during a race (it must reconnect).
