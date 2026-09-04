import pytest

import evalset

LINES = [
    '{"type": "meta", "name": "cabin"}',
    '{"type": "message", "id": "m1", "ts": "2026-03-02T18:04:00+02:00", "from": "Anna", "text": "hi"}',
    '{"type": "question", "id": "q1", "text": "who?", "expected": "Anna", "evidence": ["m1"]}',
    '{"type": "question", "id": "q2", "text": "colour?", "answerable": false, "category": "abstention"}',
    "",
]


def test_parse_splits_records_and_fills_defaults():
    meta, messages, questions = evalset.parse(LINES)
    assert meta["name"] == "cabin" and len(messages) == 1
    assert questions[0]["answerable"] is True and questions[0]["category"] == "recall"
    assert questions[1]["answerable"] is False
    with pytest.raises(ValueError):
        evalset.parse(['{"type": "nonsense"}'])


def test_parse_verdict_tolerates_fences_and_junk():
    assert evalset.parse_verdict('```json\n{"correct": true, "why": "same"}\n```') is True
    assert evalset.parse_verdict('{"correct": false}') is False
    assert evalset.parse_verdict("I think so") is None
    assert evalset.parse_verdict('{"correct": "yes"}') is None


def test_metrics_separate_accuracy_abstention_and_false_refusal():
    results = [
        {"answerable": True, "correct": True, "cited": True, "refused": False, "latency_ms": 100},
        {"answerable": True, "correct": False, "cited": False, "refused": False, "latency_ms": 200},
        {"answerable": True, "correct": None, "cited": None, "refused": True, "latency_ms": 300},
        {"answerable": False, "correct": None, "cited": None, "refused": True, "latency_ms": 400},
        {"answerable": False, "correct": None, "cited": None, "refused": False, "latency_ms": 500},
    ]
    m = evalset.metrics(results)
    assert m["questions"] == 5
    assert m["answer_accuracy"] == 0.333
    assert m["citation_accuracy"] == 0.5
    assert m["abstention"] == 0.5
    assert m["false_refusal"] == 0.333
    assert m["p50_ms"] == 300 and m["p95_ms"] == 500


def test_metrics_on_an_empty_set_report_dashes():
    m = evalset.metrics([])
    assert m["answer_accuracy"] is None
    assert "–" in evalset.row("2026-09-04", "x", "model", "judge", m, None)


def test_row_renders_percentages_and_cost():
    m = evalset.metrics(
        [{"answerable": True, "correct": True, "cited": True, "refused": False, "latency_ms": 1500}]
    )
    line = evalset.row("2026-09-04", "cabin", "gemini-3.8-flash", "claude-opus-5", m, 0.00123)
    assert "100%" in line and "1500 ms" in line and "€0.00123" in line
