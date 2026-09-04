"""Run an eval set through the real pipeline and print the numbers.

    docker compose exec -T app python scripts/eval.py evals/cabin.jsonl \
        --provider 22 --judge 25

Loads the messages into a scratch group, chunks and extracts them exactly as
the app does, asks every question, grades the answers with a second provider,
and prints a markdown row for docs/EVAL.md.
"""

import argparse
import datetime as dt
import os
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asking  # noqa: E402
import chunking  # noqa: E402
import db  # noqa: E402
import evalset  # noqa: E402
import extraction  # noqa: E402
import groups  # noqa: E402
import providers  # noqa: E402


def load(name, messages, threshold, decisions):
    external_id = f"eval:{name}"
    existing = groups.get(external_id)
    if existing:
        wipe(external_id)
        groups.delete(existing["id"])
    # No --threshold means measure the default a real group would get.
    settings = {"decision_tracking": decisions}
    if threshold is not None:
        settings["confidence_threshold"] = threshold
    group = groups.create("whatsapp", external_id, name=f"eval {name}", settings=settings)
    with db.connect() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO messages (wa_msg_id, group_id, sender_jid, sender_name, body, ts) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [(m["id"], external_id, f"eval:{m['from']}", m["from"], m["text"], m["ts"]) for m in messages],
        )
    return group


def wipe(external_id):
    with db.connect() as conn:
        for table in ("facts", "chunks", "messages", "query_log"):
            conn.execute(f"DELETE FROM {table} WHERE group_id = %s", (external_id,))


def ask(group, question):
    q = SimpleNamespace(
        question=question["text"],
        group_id=group["external_id"],
        sender_jid="eval:asker",
        sender_name="eval",
        wa_msg_id=f"eval:q:{question['id']}",
        quoted_msg_id=None,
    )
    return asking.answer_in(q, group)


def grade(judge, question, res, refusal):
    refused = res["answer"] == refusal
    row = {
        "id": question["id"],
        "category": question["category"],
        "answerable": question["answerable"],
        "refused": refused,
        "latency_ms": res["timings"]["total_ms"],
        "correct": None,
        "cited": None,
        "answer": res["answer"],
    }
    if not question["answerable"] or refused:
        return row
    verdict, _, _ = providers.generate(
        judge,
        evalset.JUDGE_SYSTEM,
        evalset.judge_prompt(question["text"], question["expected"], res["answer"]),
    )
    row["correct"] = evalset.parse_verdict(verdict)
    if question.get("evidence"):
        row["cited"] = res["source_msg_id"] in question["evidence"]
    return row


def spend(external_id, since):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT coalesce(sum(cost), 0) AS answers FROM query_log "
            "WHERE group_id = %s AND id > %s AND outcome <> 'extract'",
            (external_id, since),
        ).fetchone()
    return float(row["answers"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--provider", type=int, help="provider id that answers; default is the global default")
    p.add_argument("--judge", type=int, required=True, help="provider id that grades")
    p.add_argument("--threshold", type=float, help="override the group default, to compare gates")
    p.add_argument("--no-decisions", action="store_true", help="skip fact extraction")
    p.add_argument("--keep", action="store_true", help="leave the scratch group in place")
    args = p.parse_args()

    meta, messages, questions = evalset.parse(pathlib.Path(args.path).read_text().splitlines())
    name = meta.get("name") or pathlib.Path(args.path).stem
    judge = providers.get(args.judge)
    if judge is None:
        sys.exit(f"no provider with id {args.judge}")

    group = load(name, messages, args.threshold, not args.no_decisions)
    if args.provider:
        group = groups.update(group["id"], provider_id=args.provider)
    provider = providers.resolve(group, groups.global_settings())
    if provider is None:
        sys.exit("no provider to answer with; pass --provider or set a global default")

    with db.connect() as conn:
        since = conn.execute("SELECT coalesce(max(id), 0) AS id FROM query_log").fetchone()["id"]
    print(f"{len(messages)} messages, {len(questions)} questions, answering with {provider['name']}")
    chunking.run_once()
    if not args.no_decisions:
        extraction.run_once()

    results = []
    for question in questions:
        res = ask(group, question)
        row = grade(judge, question, res, group["settings"]["refusal_text"])
        results.append(row)
        mark = "·" if row["correct"] is None else ("✓" if row["correct"] else "✗")
        print(f"  {mark} {row['id']:>3} {row['category']:<16} {row['answer'][:80]}")

    m = evalset.metrics(results)
    cost = spend(group["external_id"], since) / max(len(questions), 1)
    line = evalset.row(dt.date.today().isoformat(), name, provider["model"], judge["model"], m, cost)
    # Printed, not written: the container has no copy of the repo's docs.
    print("\n" + evalset.HEADER + "\n" + line)
    if not args.keep:
        wipe(group["external_id"])
        groups.delete(group["id"])


if __name__ == "__main__":
    main()
