# The reply race: decision models vs LLMs

A local web demo that shows how "System One" decision models such as
[Jev](https://openrouter.ai/docs/guides/community/jev-tutorial) (TypeSafe) answer a
question about hundreds of X replies faster and cheaper than LLMs, with an answer always
taken from a fixed list.

The example data: the 581 readable replies to the post presenting Episode 1 of the
"Odyssey" series made with Grok Imagine
(https://x.com/imagine/status/2113712964419063911). The question: what do people think of it?

## How the two kinds of model answer

- **An LLM writes** its answer as JSON, token by token. You pay for every generated
  token, and a malformed answer is lost (Llama 3.1 8B breaks the format on most replies).
- **A decision model chooses.** It reads the post, one reply, and typed questions
  (yes/no "Noul", "Choice" among labels, "Score"), and returns a probability for each
  possible answer. It writes nothing; only the input is billed. Code combines the answers
  into one label, and a probability between 0.3 and 0.7 marks the reply as "not sure".

## Quick start

Needs Python 3.10+ (standard library only) and an [OpenRouter](https://openrouter.ai) API key.

```bash
export OPENROUTER_API_KEY=...      # or: eval "$(pass show env/openrouter)"
python3 server.py                  # open http://127.0.0.1:8765
```

The replies (`data/replies.jsonl`) and the answer key (`data/reference.json`) are in the
repository, so the race works right after cloning. Each race costs a few cents.

## The introduction slides

`http://127.0.0.1:8765/intro.html` (linked from the race page) introduces System One models
for a non-technical audience in 15 slides: why LLMs are built for people and System One
models for code, how decision models (Jev, Clef) and extraction models (Cloudflare's
Clairic) answer, calibration, a side-by-side comparison, numbers measured in this demo
and why Sonnet only looks better, when to use which, and how to combine them. Arrow keys or the buttons move between slides;
`#n` in the URL opens slide n. A French version is at `/intro-fr.html`; each version links to the other.

## The race page

1. Pick one or more questions: the verdict on Episode 1, requests for the making-of, the
   main criticism, the tone of the reply.
2. Pick how many replies to answer (25 to 581) and how LLMs are called (20 replies per
   request, the cheapest way, or one by one like decision models).
3. Pick the models: 6 decision models (Jev 1.14, Liquid d1, Perplexity Decider Flash,
   GPT-6 Luna Decisions, Microsoft Decision 1, Cloudflare Clef Flash) and 6 LLMs
   (Mistral Nemo, Llama 3.1 8B, Gemma 3 12B, gpt-oss-20b, Claude Haiku 5.5, Claude Sonnet 5.5).
4. Start the race. Each model gets a lane that fills as it answers. Results appear as
   each model finishes: key takeaways, a scoreboard (time, cost for 1M replies, right
   answers, lost answers), podiums, how each model split the replies, and a reply-by-reply
   explorer with the decision models' probabilities next to the LLMs' raw output.

"Right answers" are measured against an answer key: Claude Sonnet 5.5 labeling every
reply (`build_reference.py`). Cohen's kappa, settled share and latency are under
"Technical details". Every race is saved in `results/`.

Only one race runs at a time. Reloading the page reconnects to the running race.

What happens behind the page during a race (in French):
[docs/comment-marche-une-course.md](docs/comment-marche-une-course.md).

## Typical results

One race saved in `results/race-20261030-132430-8d49874252.json`: 100 replies, the
question "What do they think of Episode 1?", LLMs called with 20 replies per request.

| model | kind | time | cost for 1M replies | right answers |
|---|---|---:|---:|---:|
| Claude Haiku 5.5 | LLM | 3.8 s | $15.7 | 82% |
| Jev 1.14 | decision | 6.1 s | $30.1 | 86% |
| Liquid d1 | decision | 6.9 s | $8.8 | 81% |
| gpt-oss-20b | LLM | 11.5 s | $4.3 | 83% |
| Mistral Nemo | LLM | 39.7 s | $1.4 | 74% |
| Claude Sonnet 5.5 (answer key) | LLM | 4.9 s | $313.5 | 93% |

Sonnet scores 93% and not 100% against its own answer key because the key comes from an
earlier run. Batching 20 replies per request is the cheapest way to call an LLM, since the
instructions are paid once per request; pick "One by one" on the page to compare with the
way most apps call them.

On the full CLI run (581 replies), of the replies with an opinion 72% are negative,
19% positive and 9% mixed; weighted by likes, 82% of the engagement is negative.
See `REPORT.md`.

## Files

| file | role |
|---|---|
| `server.py` | web server: model list, races, metrics, Server-Sent Events. The key never reaches the browser. |
| `engine.py` | runs one model on a set of replies (decision models: 1 reply per call, 32 in parallel; LLMs: 20 per call with 8 in parallel, or 1 per call with 32 in parallel) |
| `questions.py` | the question catalog: labels for LLMs, decision sub-questions and the code that combines them |
| `build_reference.py` | builds the answer key with Claude Sonnet 5.5 (~$0.35 for 581 replies and 4 questions) |
| `fetch_replies.py` | reads the replies of a post for free through the FxTwitter API |
| `anonymize.py` | replaces reply ids, author handles and private mentions with pseudonyms |
| `static/` | the race page (`index.html`, `style.css`, `app.js`) and the introduction slides (`intro.html`, `intro-fr.html`, `deck.css`, `deck.js`), vanilla HTML, CSS, JS |
| `classify.py`, `jev_classify.py`, `report.py` | first CLI version: one LLM or Jev on all replies, then a markdown report |

## Use another post

```bash
python3 fetch_replies.py https://x.com/<user>/status/<id>
python3 anonymize.py               # before committing the data
python3 build_reference.py         # the answer key
```

Then adapt the post description and the questions in `questions.py`.

## Data and privacy

The replies are public X posts read through FxTwitter. In the committed data, reply ids
are replaced by `r0001`..., author handles by `user-001`..., mentions of private accounts
by their pseudonym, and links to other posts by `[link to a post]`. The texts, like and
follower counts are kept, so a reply can still be found by searching its text on X.

## Limits

- FxTwitter is an unofficial service: it can rate limit, change or disappear. It returns
  X's relevance-ranked set, so only 581 of the 4,019 replies X reports could be read.
- Images and GIFs in replies are not seen by the models (marked `[media]`).
- The answer key is an LLM, not human labels. The criteria of the verdict question were
  adjusted once after looking at disagreements on these same replies, so the right-answer
  rate of decision models on this question is slightly optimistic.
- Decision models are called through OpenRouter's alpha Decisions API
  (`POST /api/alpha/decisions`), which may change.
