from retrieval import RRF_K, _fuse, _or_query


def row(i):
    return {"id": i, "content": f"c{i}", "first_msg_id": f"m{i}", "start_ts": None, "end_ts": None}


def test_or_query_keeps_the_selective_words():
    # Short words match nearly every chunk and only cost a sort; the longest
    # words are the rare ones and lead.
    assert _or_query("Who books the cabin?") == "books | cabin | who | the"
    assert _or_query("kuka tuo saunapuut") == "saunapuut | kuka | tuo"
    assert _or_query("is it on?") == ""
    assert _or_query("???") == ""
    many = _or_query("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda")
    assert len(many.split(" | ")) == 8 and "epsilon" in many


def test_fuse_rewards_chunks_in_both_lists():
    fused = _fuse([row(1), row(2)], [row(2), row(3)])
    assert [e["id"] for e in fused] == [2, 1, 3]
    assert fused[0]["source"] == "fts+vector"
    assert fused[1]["source"] == "vector"
    assert fused[0]["rrf"] == 1 / (RRF_K + 2) + 1 / (RRF_K + 1)


def test_fuse_handles_empty_legs():
    assert _fuse([], []) == []
    assert [e["id"] for e in _fuse([row(5)], [])] == [5]
