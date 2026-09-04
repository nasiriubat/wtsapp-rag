"""Push a busy group's traffic at a running app and report the latencies.

    docker compose exec -T app python scripts/loadtest.py --messages 500 --questions 50

Ingest and questions run against the HTTP API with the gateway token, so this
measures the whole path a real group takes, including the queueing that
happens when several questions arrive at once.
"""

import argparse
import concurrent.futures as cf
import os
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

import db  # noqa: E402
import evalset  # noqa: E402
import groups  # noqa: E402

APP = os.environ.get("APP_URL", "http://localhost:8000")
HEADERS = {"authorization": f"Bearer {os.environ['GATEWAY_TOKEN']}"}
LINES = [
    "Can someone bring the keys tomorrow?",
    "Kuka hoitaa kaupassa käynnin?",
    "I paid the invoice this morning.",
    "Kokous siirtyi tunnilla eteenpäin.",
    "The sauna is booked for Friday at six.",
]


def timed(client, path, body):
    start = time.perf_counter()
    res = client.post(f"{APP}{path}", json=body, headers=HEADERS, timeout=120)
    return (time.perf_counter() - start) * 1000, res.status_code


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--messages", type=int, default=500, help="a busy group's day")
    p.add_argument("--questions", type=int, default=50)
    p.add_argument("--concurrency", type=int, default=4, help="questions asked at once")
    p.add_argument("--keep", action="store_true")
    args = p.parse_args()

    external_id = "load:test"
    if (existing := groups.get(external_id)) is not None:
        groups.delete(existing["id"])
    group = groups.create("whatsapp", external_id, name="load test")
    start_ts = datetime.now(UTC) - timedelta(days=1)

    with httpx.Client() as client:
        ingest = [
            timed(
                client,
                "/ingest",
                {
                    "wa_msg_id": f"load:{i}",
                    "group_id": external_id,
                    "sender_jid": f"load:{i % 8}@s",
                    "sender_name": f"Member {i % 8}",
                    "body": LINES[i % len(LINES)],
                    "ts": (start_ts + timedelta(seconds=90 * i)).isoformat(),
                },
            )[0]
            for i in range(args.messages)
        ]
        print(
            f"ingest {args.messages}: p50 {evalset.percentile(ingest, 50):.0f} ms, "
            f"p95 {evalset.percentile(ingest, 95):.0f} ms"
        )

        import chunking

        t = time.perf_counter()
        chunking.run_once()
        with db.connect() as conn:
            n = conn.execute(
                "SELECT count(*) AS n FROM chunks WHERE group_id = %s", (external_id,)
            ).fetchone()["n"]
        print(f"chunking {args.messages} messages into {n} chunks: {(time.perf_counter() - t):.1f} s")

        def one(i):
            return timed(
                client,
                "/ask",
                {
                    "question": "@agent who has the keys?" if i % 2 else "@agent kuka maksoi laskun?",
                    "group_id": external_id,
                    "sender_jid": "load:asker@s",
                    "wa_msg_id": f"load:q:{i}",
                },
            )

        t = time.perf_counter()
        with cf.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            answers = list(pool.map(one, range(args.questions)))
        wall = time.perf_counter() - t
        latencies = [ms for ms, _ in answers]
        failed = [code for _, code in answers if code != 200]
        p50, p95 = evalset.percentile(latencies, 50), evalset.percentile(latencies, 95)
        print(
            f"ask {args.questions} at concurrency {args.concurrency}: "
            f"p50 {p50:.0f} ms, p95 {p95:.0f} ms, max {max(latencies):.0f} ms, "
            f"mean {statistics.mean(latencies):.0f} ms, "
            f"{args.questions / wall:.2f} answers/s, {len(failed)} failed"
        )

    if not args.keep:
        with db.connect() as conn:
            for table in ("facts", "chunks", "messages", "query_log"):
                conn.execute(f"DELETE FROM {table} WHERE group_id = %s", (external_id,))
        groups.delete(group["id"])


if __name__ == "__main__":
    main()
