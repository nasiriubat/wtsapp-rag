import math
import re
import threading
import time
from contextlib import nullcontext
from functools import cache

from fastembed.common.model_description import ModelSource
from fastembed.rerank.cross_encoder import TextCrossEncoder

import db
import embed
import models

RERANKER = "BAAI/bge-reranker-v2-m3"
# BAAI publishes no ONNX for v2-m3 and fastembed ships only the weaker base model,
# which misranked English test questions. This is the onnx-community export of
# the official weights, pinned to a commit in models.py; ONNX carries weights
# only, no executable code.
TextCrossEncoder.add_custom_model(
    RERANKER, sources=ModelSource(hf=models.RERANKER[0]), model_file=models.RERANKER[2][0]
)


@cache
def _reranker():
    # Lazy so importing this module in tests does not download the model.
    path = models.local_path(*models.RERANKER)
    return TextCrossEncoder(RERANKER, specific_model_path=path, threads=models.THREADS)


# Two questions may rerank at once, each on half the cores: measured at 300 ms
# for ten candidates that way, against 425 ms when one session takes every
# core and five concurrent questions fight for them.
_slots = threading.Semaphore(2)


def warm():
    _reranker()


CANDIDATES = 30
RERANK = 10
TOP = 8
RRF_K = 60
# The full-text leg: enough words to be selective, none too short to be.
MIN_WORD = 3
MAX_WORDS = 8

COLUMNS = "id, group_id, content, first_msg_id, start_ts, end_ts, document_id, source_label"
# A chunk with no group is a document shared with every group.
SCOPE = "(group_id = %s OR group_id IS NULL)"


def _ms(t):
    return round((time.perf_counter() - t) * 1000)


def _or_query(question):
    # The 'simple' config keeps stopwords, so an AND query dies on "who" or "the".
    # OR the words and let ts_rank_cd reward the chunks that match most. Words
    # under three letters match nearly every chunk and only cost a sort, so
    # they go; the longest words stay, because long words are the rare ones.
    words = []
    for w in re.findall(r"\w+", question.lower()):
        if len(w) >= MIN_WORD and w not in words:
            words.append(w)
    words = sorted(words, key=len, reverse=True)[:MAX_WORDS]
    return " | ".join(words)


def _fuse(vector_rows, fts_rows):
    fused = {}
    for source, rows in (("vector", vector_rows), ("fts", fts_rows)):
        for rank, row in enumerate(rows):
            entry = fused.setdefault(row["id"], {**row, "rrf": 0.0, "source": set()})
            entry["rrf"] += 1 / (RRF_K + rank + 1)
            entry["source"].add(source)
    ranked = sorted(fused.values(), key=lambda e: e["rrf"], reverse=True)
    for e in ranked:
        e["source"] = "+".join(sorted(e["source"]))
    return ranked


def _candidates(conn, group_id, question, qvec):
    """Both legs, fused, for one group."""
    with conn.transaction():
        # An HNSW scan finds the nearest neighbours of the whole table and then
        # filters by group, so with many groups the asking group could get back
        # a handful of the rows it asked for. Iterative scans keep walking the
        # graph until the filter is satisfied.
        conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        vector_rows = conn.execute(
            f"SELECT {COLUMNS} FROM chunks WHERE {SCOPE} ORDER BY embedding <=> %s::vector LIMIT %s",
            (group_id, qvec, CANDIDATES),
        ).fetchall()
    tsquery = _or_query(question)
    fts_rows = []
    if tsquery:
        fts_rows = conn.execute(
            f"""
            SELECT {COLUMNS} FROM chunks
            WHERE {SCOPE} AND tsv @@ to_tsquery('simple', %s)
            ORDER BY ts_rank_cd(tsv, to_tsquery('simple', %s)) DESC LIMIT %s
            """,
            (group_id, tsquery, tsquery, CANDIDATES),
        ).fetchall()
    return _fuse(vector_rows, fts_rows)


def _rerank(question, candidates):
    if not candidates:
        return []
    with _slots:
        logits = _reranker().rerank(question, [c["content"] for c in candidates])
    for c, logit in zip(candidates, logits, strict=True):
        # Sigmoid so CONFIDENCE_THRESHOLD reads as a probability, not a raw logit.
        c["score"] = 1 / (1 + math.exp(-float(logit)))
    return sorted(candidates, key=lambda c: c["score"], reverse=True)


def search(group_id, question, conn=None):
    """Ranked chunks and timings. Pass `conn` to reuse the caller's connection."""
    timings = {}
    t = time.perf_counter()
    qvec = embed.literal(embed.query(question))
    timings["embed_ms"] = _ms(t)

    t = time.perf_counter()
    with nullcontext(conn) if conn is not None else db.connect() as c:
        candidates = _candidates(c, group_id, question, qvec)[:RERANK]
    timings["sql_ms"] = _ms(t)

    t = time.perf_counter()
    ranked = _rerank(question, candidates)[:TOP]
    timings["rerank_ms"] = _ms(t)
    return ranked, timings


PER_GROUP = 4


def search_many(group_ids, question, conn=None):
    """One question against several groups, for a private question: one
    embedding, the cheap legs per group, one rerank over the merged shortlist.
    Returns (group_id, ranked chunks, timings) for the best group, or None."""
    timings = {}
    t = time.perf_counter()
    qvec = embed.literal(embed.query(question))
    timings["embed_ms"] = _ms(t)

    t = time.perf_counter()
    shortlist = []
    with nullcontext(conn) if conn is not None else db.connect() as c:
        for gid in group_ids:
            for candidate in _candidates(c, gid, question, qvec)[:PER_GROUP]:
                # A shared document has no group of its own; it counts for the
                # group it was found through.
                shortlist.append({**candidate, "asked_in": gid})
    timings["sql_ms"] = _ms(t)

    t = time.perf_counter()
    ranked = _rerank(question, shortlist)
    timings["rerank_ms"] = _ms(t)
    if not ranked:
        return None
    best = ranked[0]["asked_in"]
    return best, [c for c in ranked if c["asked_in"] == best][:TOP], timings
