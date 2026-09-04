"""Eval sets: parse a .jsonl set, judge an answer, and turn results into the
numbers we publish. Everything here is pure so it can be tested without a
provider or a database."""

import json
import re

JUDGE_SYSTEM = """You grade one answer from a group-chat assistant.
You are given the question, the reference answer, and the assistant's answer.
Reply with JSON only: {"correct": true|false, "why": "<a few words>"}.
Correct means it states the same facts as the reference. Extra detail is fine,
and so is a different language or wording. Missing or contradicting a fact in
the reference is not correct. Saying it does not know is not correct."""


def parse(lines):
    """Returns (meta, messages, questions) from an eval .jsonl file."""
    meta, messages, questions = {}, [], []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rec = json.loads(line)
        kind = rec.get("type")
        if kind == "meta":
            meta = rec
        elif kind == "message":
            messages.append(rec)
        elif kind == "question":
            questions.append({"answerable": True, "category": "recall", **rec})
        else:
            raise ValueError(f"unknown record type {kind!r}")
    return meta, messages, questions


def judge_prompt(question, expected, given):
    return f"Question: {question}\n\nReference answer: {expected}\n\nAssistant's answer: {given}"


def parse_verdict(text):
    """True, False, or None when the judge did not answer in the agreed shape."""
    body = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        value = json.loads(body).get("correct")
    except (json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, bool) else None


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    i = min(len(ordered) - 1, int(round((p / 100) * (len(ordered) - 1))))
    return ordered[i]


def metrics(results):
    """`results`: dicts with answerable, correct, cited, refused, latency_ms."""
    answerable = [r for r in results if r["answerable"]]
    unanswerable = [r for r in results if not r["answerable"]]
    answered = [r for r in answerable if not r["refused"]]
    cited = [r for r in answered if r["cited"] is not None]
    return {
        "questions": len(results),
        "answer_accuracy": _share([r["correct"] is True for r in answerable]),
        "citation_accuracy": _share([r["cited"] for r in cited]),
        "abstention": _share([r["refused"] for r in unanswerable]),
        "false_refusal": _share([r["refused"] for r in answerable]),
        "p50_ms": percentile([r["latency_ms"] for r in results], 50),
        "p95_ms": percentile([r["latency_ms"] for r in results], 95),
    }


def _share(flags):
    return round(sum(1 for f in flags if f) / len(flags), 3) if flags else None


def _cell(value, suffix=""):
    return (
        "–"
        if value is None
        else f"{value:.0%}{suffix}"
        if suffix == "" and value <= 1
        else f"{value}{suffix}"
    )


HEADER = (
    "| Run | Set | Answering model | Judge | Questions | Answer accuracy | Citation accuracy "
    "| Abstention | False refusal | p50 | p95 | Cost/question |\n"
    "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"
)


def row(when, name, model, judge, m, cost_per_question):
    cost = "–" if cost_per_question is None else f"€{cost_per_question:.5f}"
    return (
        f"| {when} | {name} | {model} | {judge} | {m['questions']} | "
        f"{_cell(m['answer_accuracy'])} | {_cell(m['citation_accuracy'])} | "
        f"{_cell(m['abstention'])} | {_cell(m['false_refusal'])} | "
        f"{_cell(m['p50_ms'], ' ms')} | {_cell(m['p95_ms'], ' ms')} | {cost} |"
    )
