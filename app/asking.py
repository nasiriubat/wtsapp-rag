"""The decision tree behind /ask: refuse, correct, answer, or stay silent.
main.py owns the HTTP shape; this owns what happens to a question."""

import re
import time
import uuid
from collections import deque
from types import SimpleNamespace

import answer
import budget
import db
import facts
import gateway_state
import groups
import observe
import providers
import query_log
import retrieval

NO_PROVIDER = "No LLM provider is configured yet. Ask the admin to add one."
NO_DM_GROUP = "I can only answer privately about groups you are in and that allow it."
# "no" and "ei" only count with punctuation, so "no idea what…" is a question.
CORRECTION = re.compile(
    r"^\s*(?:(?:wrong|nope|actually|correction|väärin|korjaus)[\s,.:!-]*|(?:no|ei)[,.:!-]\s*)", re.I
)
DM_CANDIDATES = 5
# Questions one person may ask in a window, across every group. Enough for a
# lively evening, not enough to loop the bot into a bill.
RATE_LIMIT, RATE_WINDOW = 10, 600
SLOW_DOWN = "That is a lot of questions in a row. Ask again in a few minutes."
_asked = {}  # sender_jid -> deque of monotonic times


def throttle(q, now=None):
    """The response for a sender over the limit, or None. Checked before any
    retrieval runs, so a flood costs nothing but this lookup."""
    now = time.monotonic() if now is None else now
    if len(_asked) > 10_000:
        for k in [k for k, v in _asked.items() if not v]:
            _asked.pop(k, None)
    recent = _asked.setdefault(q.sender_jid, deque())
    while recent and now - recent[0] > RATE_WINDOW:
        recent.popleft()
    if len(recent) >= RATE_LIMIT:
        observe.count("ask_total", outcome="rate_limited")
        query_log.record(
            group_id=q.group_id,
            sender_jid=q.sender_jid,
            question=q.question,
            answer=SLOW_DOWN,
            outcome="rate_limited",
        )
        return {"answer": SLOW_DOWN, "quote": None, "outcome": "rate_limited"}
    recent.append(now)
    return None


def _words(text):
    return {w for w in re.findall(r"\w+", (text or "").lower()) if len(w) > 3}


def best_source(messages, text):
    """The message in an episode the answer most likely came from: the one
    sharing the most distinctive words with it. The episode's first message is
    the fallback, and it is what a tie falls back to."""
    if not messages:
        return None
    wanted = _words(text)
    return max(messages, key=lambda m: len(wanted & _words(m["body"])) if wanted else 0)


def _source(chunk, text, conn):
    rows = conn.execute(
        "SELECT wa_msg_id, sender_jid, sender_name, is_bot, body, ts FROM messages "
        "WHERE group_id = %s AND ts BETWEEN %s AND %s AND NOT is_bot ORDER BY ts",
        (chunk["group_id"], chunk["start_ts"], chunk["end_ts"]),
    ).fetchall()
    return best_source(rows, text)


def _cite(text, src, group_name=None):
    # Imported messages have synthetic ids, so no channel can resolve a quote to
    # them; a private answer cannot quote across chats either. Text citation then.
    if src["wa_msg_id"].startswith("import:") or group_name is not None:
        first_line = (src["body"] or "").splitlines()[0]
        where = f"In {group_name}, " if group_name else "From "
        return f'{where}{src["ts"]:%d %b %Y}, {src["sender_name"]}: "{first_line}"\n\n{text}', None
    return text, {k: src[k] for k in ("wa_msg_id", "sender_jid", "is_bot", "body")}


def _quoted_bot_message(group_id, quoted_msg_id):
    with db.connect() as conn:
        return conn.execute(
            "SELECT body, ts FROM messages WHERE group_id = %s AND wa_msg_id = %s AND is_bot",
            (group_id, quoted_msg_id),
        ).fetchone()


def try_correction(q, group):
    """A reply to one of our answers that starts with "wrong"/"actually" is a
    correction: stored as a fact that supersedes what that answer was built on."""
    m = CORRECTION.match(q.question)
    if not m or not q.quoted_msg_id:
        return None
    statement = q.question[m.end() :].strip()
    if not statement:
        return None
    quoted = _quoted_bot_message(q.group_id, q.quoted_msg_id)
    if quoted is None:
        return None
    with db.connect() as conn:
        original = conn.execute(
            "SELECT retrieved FROM query_log WHERE group_id = %s AND answer = %s ORDER BY id DESC LIMIT 1",
            (q.group_id, quoted["body"]),
        ).fetchone()
    related = (original["retrieved"] or {}).get("facts", []) if original else []
    facts.correct(q.group_id, statement, q.sender_jid, q.wa_msg_id, quoted["ts"], related)
    observe.count("ask_total", outcome="correction")
    query_log.record(
        group_id=q.group_id,
        sender_jid=q.sender_jid,
        question=q.question,
        answer=statement,
        outcome="correction",
    )
    return {"answer": group["settings"]["correction_ack"], "quote": None, "outcome": "correction"}


def answer_in(q, group, cite_group=False, found=None):
    """Answer a question from one group. `found` reuses a search already done."""
    with db.connect() as conn:
        return _answer_in(conn, q, group, cite_group, found)


def _answer_in(conn, q, group, cite_group, found):
    # One connection for the whole question. Each step used to open its own,
    # eight or nine per answer, and every one is a backend process in Postgres.
    s = group["settings"]
    t0 = time.perf_counter()
    chunks, timings = found or retrieval.search(group["external_id"], q.question, conn=conn)
    confidence = chunks[0]["score"] if chunks else 0.0
    text, quote, tokens, cost, provider = s["refusal_text"], None, (None, None), None, None
    outcome, fact_ids, source_id = "refused", [], None
    if confidence >= s["confidence_threshold"]:
        global_settings = groups.global_settings()
        provider = providers.resolve(group, global_settings)
        if provider is None:
            text, outcome = NO_PROVIDER, "no_provider"
        elif budget.exceeded(group, global_settings):
            text, outcome = budget.BUDGET_TEXT, "budget"
        else:
            t = time.perf_counter()
            fact_rows = (
                facts.search(group["external_id"], q.question, conn=conn) if s["decision_tracking"] else []
            )
            timings["facts_ms"] = round((time.perf_counter() - t) * 1000)
            fact_ids = [r["id"] for r in fact_rows]
            t = time.perf_counter()
            text, *tokens = answer.generate(q.question, chunks, provider, s, fact_rows)
            timings["llm_ms"] = round((time.perf_counter() - t) * 1000)
            cost = providers.cost(provider, *tokens)
            if answer.is_refusal(text):
                text = s["refusal_text"]
            elif answer.is_document(chunks[0]):
                # A document has no message to quote, so the file name is the citation.
                text = f"From {chunks[0]['source_label']}\n\n{text}"
                outcome = "dm" if cite_group else "answered"
            else:
                src = _source(chunks[0], text, conn)
                if src is None:
                    # The episode was erased between search and answer. The call
                    # was still made and paid for, so it is logged like any other.
                    text = s["refusal_text"]
                else:
                    source_id = src["wa_msg_id"]
                    text, quote = _cite(text, src, group["name"] if cite_group else None)
                    outcome = "dm" if cite_group else "answered"
    timings["total_ms"] = round((time.perf_counter() - t0) * 1000)
    observe.count("ask_total", outcome=outcome)
    observe.observe_latency(timings["total_ms"] / 1000)
    query_log.record(
        group_id=group["external_id"],
        sender_jid=q.sender_jid,
        question=q.question,
        answer=text,
        outcome=outcome,
        chunks=chunks,
        fact_ids=fact_ids,
        timings=timings,
        confidence=confidence,
        tokens=tuple(tokens),
        provider=provider,
        cost=cost,
        conn=conn,
    )
    return {
        "answer": text,
        "quote": quote,
        "outcome": outcome,
        "confidence": confidence,
        "timings": timings,
        "source_msg_id": source_id,
        "chunks": chunks,
    }


PANEL_SENDER = "admin:panel"


def ask_from_panel(group, question):
    """The admin asking from the browser: the same path a member's question
    takes, logged like one, but never throttled and never sent anywhere."""
    q = SimpleNamespace(
        question=question,
        group_id=group["external_id"],
        sender_jid=PANEL_SENDER,
        sender_name="admin",
        wa_msg_id=f"panel:{uuid.uuid4()}",
        quoted_msg_id=None,
    )
    return answer_in(q, group)


def answer_privately(q):
    """Pick the member's group that matches the question best and answer from
    it with a text citation. Private questions are never stored as messages."""
    candidates = groups.dm_candidates(q.sender_jid, gateway_state.members())
    if not candidates:
        observe.count("ask_total", outcome="dm_unknown")
        return {"answer": NO_DM_GROUP, "quote": None, "outcome": "dm_unknown"}
    by_id = {g["external_id"]: g for g in candidates[:DM_CANDIDATES]}
    with db.connect() as conn:
        found = retrieval.search_many(list(by_id), q.question, conn=conn)
        if found is None:
            # Nothing indexed in any of their groups yet: answer from the first
            # with an empty search, so the refusal is logged like any other.
            group = candidates[0]
            return _answer_in(conn, q, group, True, ([], {}))
        best, chunks, timings = found
        return _answer_in(conn, q, by_id[best], True, (chunks, timings))
