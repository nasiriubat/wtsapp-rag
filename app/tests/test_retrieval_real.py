"""Retrieval end to end with real embeddings. The reranker is faked (2 GB is
too much for a unit test); the embedding model is the real one, fetched once
into MODELS_DIR. What this checks is everything between the question and the
rerank: the vector leg, the full-text leg, fusion, the scope, the sigmoid."""

import os
import uuid

import pytest
from conftest import needs_db

pytestmark = [needs_db, pytest.mark.skipif(not os.environ.get("MODELS_DIR"), reason="set MODELS_DIR")]

SENTENCES = [
    "Mikko booked the Kuusamo cabin for the first weekend of October.",
    "Anna paid the electricity invoice on Tuesday morning.",
    "The sauna stove needs a new heater element before winter.",
    "Kokous siirtyi ensi viikon torstaille kello kuudeksi.",
]


@pytest.fixture()
def corpus(client, monkeypatch):
    """Twenty groups with the same four sentences, plus one shared document,
    so the asking group is one twentieth of the table."""
    import db
    import embed
    import retrieval

    class FakeReranker:
        # Lexical overlap stands in for the cross-encoder.
        def rerank(self, question, docs):
            words = set(question.lower().split())
            return [float(len(words & set(d.lower().split()))) for d in docs]

    monkeypatch.setattr(retrieval, "_reranker", lambda: FakeReranker())
    run = uuid.uuid4().hex[:8]
    gids = [f"real-{run}-{i}@g.us" for i in range(20)]
    vectors = embed.passages(SENTENCES)
    with db.connect() as conn:
        for gid in gids:
            for sentence, vector in zip(SENTENCES, vectors, strict=True):
                conn.execute(
                    "INSERT INTO chunks (group_id, content, first_msg_id, start_ts, end_ts, embedding) "
                    "VALUES (%s, %s, 'm', now(), now(), %s::vector)",
                    (gid, f"Someone: {sentence}", embed.literal(vector)),
                )
        shared = "rules.md\nQuiet hours in the cabin start at ten in the evening."
        conn.execute(
            "INSERT INTO chunks (group_id, content, source_label, embedding) "
            "VALUES (NULL, %s, 'rules.md', %s::vector)",
            (shared, embed.passage_literal(shared)),
        )
    yield gids
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM chunks WHERE group_id LIKE %s OR source_label = 'rules.md'", (f"real-{run}-%",)
        )


def test_the_asking_group_gets_its_full_candidate_list_among_twenty_groups(corpus):
    import db
    import embed
    import retrieval

    qvec = embed.literal(embed.query("who booked the cabin?"))
    with db.connect() as conn:
        rows = retrieval._candidates(conn, corpus[0], "who booked the cabin?", qvec)
    # Four own chunks plus the shared document: every one of them, not a
    # handful left over after a global nearest-neighbour walk.
    assert {r["group_id"] for r in rows} <= {corpus[0], None}
    assert len(rows) == 5


def test_search_ranks_the_semantically_right_chunk_first(corpus):
    import retrieval

    ranked, timings = retrieval.search(corpus[3], "who booked the cabin for October?")
    assert ranked and "Kuusamo cabin" in ranked[0]["content"]
    assert 0 < ranked[0]["score"] < 1 and timings["rerank_ms"] >= 0

    # Across languages the vector leg has to carry it: the fake reranker sees no
    # shared words, so this checks recall, not rank.
    ranked, _ = retrieval.search(corpus[3], "Kuka varasi mökin lokakuuksi?")
    assert any("Kuusamo cabin" in c["content"] for c in ranked[:3])

    ranked, _ = retrieval.search(corpus[3], "when do quiet hours start?")
    assert ranked[0]["source_label"] == "rules.md"


def test_search_many_reranks_once_and_names_the_group(corpus):
    import retrieval

    best, ranked, timings = retrieval.search_many(corpus[:5], "who paid the invoice?")
    assert best in corpus[:5] and "invoice" in ranked[0]["content"]
    assert all(c["asked_in"] == best for c in ranked)
