"""Local handbook retrieval; independent of records, sessions, and writes."""

import json
import math
import re
from collections import Counter
from pathlib import Path

HANDBOOK = json.loads((Path(__file__).parent / "handbook.json").read_text())

STOP_WORDS = set(
    "a an the is are was were be been being to of for in on at with and or how what when where do does can could should would i my me we our your it this that from by as have has about policy please works fictional".split()
)


def tokens(text):
    return [t for t in re.findall(r"[a-z]+", text.lower()) if t not in STOP_WORDS]


def retrieve(query):
    """Small local TF-IDF vector index; lexical similarity, not semantic embeddings."""
    docs = [Counter(tokens(p["title"] + " " + p["text"])) for p in HANDBOOK]
    terms = set().union(*docs)
    idf = {t: math.log((1 + len(docs)) / (1 + sum(t in d for d in docs))) + 1 for t in terms}

    def vector(counts):
        v = {t: n * idf[t] for t, n in counts.items() if t in idf}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        return {t: x / norm for t, x in v.items()}

    q = vector(Counter(tokens(query)))
    scores = [sum(q.get(t, 0) * w for t, w in vector(d).items()) for d in docs]
    best = max(scores, default=0)
    return [
        HANDBOOK[i]
        for i in sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)[:2]
        if scores[i] >= max(0.16, best * 0.65)
    ]
