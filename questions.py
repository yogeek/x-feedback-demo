"""Question catalog for the race UI. All wording lives here.

Each question has:
- `labels`: the fixed list every model must answer from (label -> description).
  LLMs get it as an enum in a JSON schema.
- `decision`: the typed sub-questions sent to decision models (Jev & co).
- `combine(answers)`: code that turns the sub-answers into a probability per
  label. The final label and the "settled" flag come from that distribution.
"""

POST = {
    "author": "Grok Imagine (@imagine), xAI's video generation product",
    "text": ("Watch Episode 1 of our Odyssey series made with Grok Imagine. Let us know in "
             "the comments if you'd like a full breakdown of how it was done!"),
    "video": "Episode 1 of 'Odyssey', an AI-generated series episode made with Grok Imagine",
}
CONTEXT = ("X (Twitter) replies to a post by @imagine announcing Episode 1 of \"Odyssey\", "
           "an AI-generated video made with Grok Imagine.")
YES, NO = 0.7, 0.3


def _band(p):
    return p > YES or p < NO


def _opinion(a):
    on, has = a["on_topic"]["noul"], a["has_opinion"]["noul"]
    ch = a["opinion"]["probabilities"]
    dist = {"off_topic": 1 - on, "neutral": on * (1 - has)}
    for k in ("positive", "negative", "mixed"):
        dist[k] = on * has * ch.get(k, 0)
    return dist, _band(on) and _band(has)


def _breakdown(a):
    p = a["wants"]["noul"]
    return {"yes": p, "no": 1 - p}, _band(p)


def _criticism(a):
    c = a["criticizes"]["noul"]
    dist = {"none": 1 - c}
    for k, v in a["target"]["probabilities"].items():
        dist[k] = c * v
    return dist, _band(c)


def _tone(a):
    probs = a["level"]["probabilities"]
    levels = list(QUESTIONS["tone"]["labels"])
    dist = {levels[int(i)]: v for i, v in probs.items()}
    return dist, max(dist.values()) >= 0.6


QUESTIONS = {
    "opinion": {
        "title": "What do they think of Episode 1?",
        "summary": "The overall verdict of each reply on the video.",
        "primitive": "2 Nouls + 1 Choice",
        "labels": {
            "positive": "likes it, impressed, praise, excited for more",
            "negative": "dislikes it, mocks it, calls it slop/bad/boring",
            "mixed": "both praise and criticism (e.g. 'impressive tech but bad story')",
            "neutral": "no opinion: questions, requests for the breakdown, tags, facts",
            "off_topic": "unrelated, spam, promotion, or politics with no link to the video",
        },
        "decision": {
            "on_topic": {
                "type": "noul",
                "instructions": "Does `reply` respond to the Odyssey Episode 1 video or to `post`?",
                "criteria": {
                    "true": "The reply reacts to the video, its quality, AI video, or how it was "
                            "made, or only tags people who made it, such as @glumlot_.",
                    "false": "The reply is spam, self-promotion, or about an unrelated subject, "
                             "such as politics that never mentions the video.",
                },
            },
            "has_opinion": {
                "type": "noul",
                "instructions": "Does `reply` judge the Odyssey Episode 1 video?",
                "criteria": {
                    "true": "The commenter praises, criticizes, mocks, or rates the video, "
                            "including through sarcasm.",
                    "false": "The commenter only asks a question, asks for the breakdown, tags "
                             "someone, or states a fact, without saying whether the video is good.",
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
        },
        "combine": _opinion,
    },
    "breakdown": {
        "title": "Do they ask for the making-of?",
        "summary": "The post asks who wants a breakdown of how it was made.",
        "primitive": "1 Noul",
        "labels": {
            "yes": "asks for the breakdown or asks how the video was made",
            "no": "does not ask how the video was made",
        },
        "decision": {
            "wants": {
                "type": "noul",
                "instructions": "Does `reply` ask for the breakdown of how the video was made?",
                "criteria": {
                    "true": "The commenter says they want the breakdown or asks how it was made.",
                    "false": "The commenter does not ask how the video was made.",
                },
            },
        },
        "combine": _breakdown,
    },
    "criticism": {
        "title": "What do they criticize most?",
        "summary": "The main weak point named by critics, to know what to fix.",
        "primitive": "1 Noul + 1 Choice",
        "labels": {
            "story_writing": "the story, script, dialogue, or characters",
            "visuals": "the images look fake, uncanny, inconsistent, dark, or low quality",
            "acting_faces": "faces, expressions, lip sync, or acting",
            "editing_pacing": "editing, cuts, pacing, music, or sound",
            "accuracy": "historical or mythological accuracy (costumes, Homer's story)",
            "ai_itself": "AI-made video as such: slop, no soul, theft from artists",
            "none": "no criticism of the video",
        },
        "decision": {
            "criticizes": {
                "type": "noul",
                "instructions": "Does `reply` criticize the Odyssey Episode 1 video?",
                "criteria": {
                    "true": "The commenter names something bad about the video or mocks it.",
                    "false": "The commenter praises the video, asks a question, or talks about "
                             "something else.",
                },
            },
            "target": {
                "type": "choice",
                "instructions": "What does `reply` criticize most about the Odyssey Episode 1 video?",
                "criteria": {
                    "story_writing": "The story, script, dialogue, or characters.",
                    "visuals": "The images look fake, uncanny, inconsistent, dark, or low quality.",
                    "acting_faces": "Faces, expressions, lip sync, or acting.",
                    "editing_pacing": "Editing, cuts, pacing, music, or sound.",
                    "accuracy": "Historical or mythological accuracy, such as costumes or "
                                "departures from Homer.",
                    "ai_itself": "That it is AI-made at all: slop, soulless, theft from artists, "
                                 "with no specific flaw named.",
                },
            },
        },
        "combine": _criticism,
    },
    "tone": {
        "title": "How civil is the reply?",
        "summary": "Moderation view: from polite to hostile.",
        "primitive": "1 Score",
        "labels": {
            "civil": "polite, even when critical",
            "rude": "swearing, dismissive, or sarcastic insults about the video",
            "hostile": "insults or attacks people (the team, xAI, Elon Musk, other users)",
        },
        "decision": {
            "level": {
                "type": "score",
                "instructions": "How civil is the commenter in `reply`?",
                "criteria": [
                    "The commenter writes politely, even when they criticize the video.",
                    "The commenter swears or dismisses the video with insults about the work.",
                    "The commenter insults or attacks people, such as the team, xAI, or other users.",
                ],
            },
        },
        "combine": _tone,
    },
}


def decide(qid, answers):
    """Sub-answers -> (label, settled, distribution over labels)."""
    dist, settled = QUESTIONS[qid]["combine"](answers)
    dist = {k: round(dist.get(k, 0.0), 4) for k in QUESTIONS[qid]["labels"]}
    return max(dist, key=dist.get), settled, dist


def public_catalog():
    return [{"id": qid, "title": q["title"], "summary": q["summary"],
             "primitive": q["primitive"], "labels": q["labels"]}
            for qid, q in QUESTIONS.items()]
