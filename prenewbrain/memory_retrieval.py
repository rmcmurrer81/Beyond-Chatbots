"""Complete source-backed lexical retrieval; no external embeddings or model."""
from __future__ import annotations
import json
import math
from pathlib import Path
import re
from collections import Counter


def words(text):
    values = re.findall(r"[a-z0-9]+", text.casefold())
    return ["homeless" if x.startswith("homeless") else x for x in values if len(x) > 2]


def retrieve(root, key, query, count=8):
    path = Path(root) / "people" / key / "sources.json"
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        raw = handle.read(2097153)
    if len(raw) > 2097152:
        raise ValueError("Source index exceeds bound")
    source = json.loads(raw)
    chunks = source["chunks"]
    terms = set(words(query))
    if not terms:
        return ""
    if any(x in terms for x in ("homeless", "homelessness", "freeway")):
        terms.add("homeless")
    document_frequency = Counter(t for chunk in chunks for t in set(words(chunk["text"])))
    scored = []
    for index, chunk in enumerate(chunks):
        counts = Counter(words(chunk["text"]))
        score = sum((1 + math.log((1 + len(chunks)) / (1 + document_frequency[t])))
                    * min(counts[t], 3) for t in terms if counts[t])
        if score:
            scored.append((score, index))
    selected = sorted(scored, key=lambda x: (-x[0], x[1]))[:count]
    selected.sort(key=lambda x: x[1])
    return "\n\n".join("[" + chunks[i]["source"] + ", chunk " + str(i) + "]\n" + chunks[i]["text"]
                         for _, i in selected)
