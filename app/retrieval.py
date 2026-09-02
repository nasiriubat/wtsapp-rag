import math
import re
import time

from fastembed.common.model_description import ModelSource
from fastembed.rerank.cross_encoder import TextCrossEncoder

import db
import embed

RERANKER = "BAAI/bge-reranker-v2-m3"
# BAAI publishes no ONNX for v2-m3 and fastembed ships only the weaker base model,
# which misranked English test questions. This is a third-party O3 export of the
# official weights; ONNX carries weights only, no executable code.
TextCrossEncoder.add_custom_model(
    RERANKER,
    sources=ModelSource(hf="EmbeddedLLM/bge-reranker-v2-m3-onnx-o3-cpu"),
    model_file="model.onnx",
    additional_files=["model.onnx.data"],
)
_reranker = TextCrossEncoder(RERANKER, cache_dir="/models")

CANDIDATES = 30
# Measured on a laptop CPU: 10 candidates rerank in 3.3 s, 20 in 6.3 s.
RERANK = 10
TOP = 8
RRF_K = 60

COLUMNS = "id, content, first_msg_id, start_ts, end_ts"


def _ms(t):
    return round((time.perf_counter() - t) * 1000)


def _or_query(question):
    # The 'simple' config keeps stopwords, so an AND query dies on "who" or "the".
    # OR them all and let ts_rank_cd reward the chunks that match most.
    words = re.findall(r"\w+", question.lower())
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


def search(group_id, question):
    timings = {}
    t = time.perf_counter()
    qvec = embed.literal(embed.query(question))
    timings["embed_ms"] = _ms(t)

    t = time.perf_counter()
    with db.connect() as conn:
        vector_rows = conn.execute(
            f"SELECT {COLUMNS} FROM chunks WHERE group_id = %s ORDER BY embedding <=> %s::vector LIMIT %s",
            (group_id, qvec, CANDIDATES),
        ).fetchall()
        tsquery = _or_query(question)
        fts_rows = conn.execute(
            f"""
            SELECT {COLUMNS} FROM chunks
            WHERE group_id = %s AND tsv @@ to_tsquery('simple', %s)
            ORDER BY ts_rank_cd(tsv, to_tsquery('simple', %s)) DESC LIMIT %s
            """,
            (group_id, tsquery, tsquery, CANDIDATES),
        ).fetchall() if tsquery else []
    timings["sql_ms"] = _ms(t)

    candidates = _fuse(vector_rows, fts_rows)[:RERANK]
    t = time.perf_counter()
    logits = _reranker.rerank(question, [c["content"] for c in candidates]) if candidates else []
    for c, logit in zip(candidates, logits):
        # Sigmoid so CONFIDENCE_THRESHOLD reads as a probability, not a raw logit.
        c["score"] = 1 / (1 + math.exp(-float(logit)))
    timings["rerank_ms"] = _ms(t)

    ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)[:TOP]
    return ranked, timings
