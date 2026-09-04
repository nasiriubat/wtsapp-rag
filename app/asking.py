"""The decision tree behind /ask: refuse, correct, answer, or stay silent.
main.py owns the HTTP shape; this owns what happens to a question."""

import json
import re
import time

import answer
import budget
import db
import facts
import gateway_state
import groups
import observe
import providers
import retrieval

NO_PROVIDER = "No LLM provider is configured yet. Ask the admin to add one."
NO_DM_GROUP = "I can only answer privately about groups you are in and that allow it."
# "no" and "ei" only count with punctuation, so "no idea what…" is a question.
CORRECTION = re.compile(
    r"^\s*(?:(?:wrong|nope|actually|correction|väärin|korjaus)[\s,.:!-]*|(?:no|ei)[,.:!-]\s*)", re.I
)


def _source(chunk):
    with db.connect() as conn:
        return conn.execute(
            "SELECT wa_msg_id, sender_jid, sender_name, is_bot, body, ts FROM messages "
            "WHERE group_id = %s AND wa_msg_id = %s",
            (chunk["group_id"], chunk["first_msg_id"]),
        ).fetchone()


def _cite(text, src, group_name=None):
    # Imported messages have synthetic ids, so no channel can resolve a quote to
    # them; a private answer cannot quote across chats either. Text citation then.
    if src["wa_msg_id"].startswith("import:") or group_name is not None:
        first_line = (src["body"] or "").splitlines()[0]
        where = f"In {group_name}, " if group_name else "From "
        return f'{where}{src["ts"]:%d %b %Y}, {src["sender_name"]}: "{first_line}"\n\n{text}', None
    return text, {k: src[k] for k in ("wa_msg_id", "sender_jid", "is_bot", "body")}


def log_question(
    q, group_id, chunks, timings, text, confidence, tokens, provider, cost, outcome, fact_ids=()
):
    retrieved = {
        "chunks": [{"chunk_id": c["id"], "score": c["score"], "source": c["source"]} for c in chunks],
        "facts": list(fact_ids),
        "timings": timings,
    }
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO query_log
              (group_id, sender_jid, question, retrieved, answer, confidence,
               tokens_in, tokens_out, latency_ms, provider_id, cost, outcome)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                group_id,
                q.sender_jid,
                q.question,
                json.dumps(retrieved),
                text,
                confidence,
                tokens[0],
                tokens[1],
                timings.get("total_ms"),
                provider["id"] if provider else None,
                cost,
                outcome,
            ),
        )


def _quoted_bot_message(group_id, quoted_msg_id):
    if not quoted_msg_id:
        return None
    with db.connect() as conn:
        return conn.execute(
            "SELECT body, ts FROM messages WHERE group_id = %s AND wa_msg_id = %s AND is_bot",
            (group_id, quoted_msg_id),
        ).fetchone()


def try_correction(q, group):
    """A reply to one of our answers that starts with "wrong"/"actually" is a
    correction: stored as a fact that supersedes what that answer was built on."""
    m = CORRECTION.match(q.question)
    quoted = _quoted_bot_message(q.group_id, q.quoted_msg_id)
    if not m or quoted is None:
        return None
    statement = q.question[m.end() :].strip()
    if not statement:
        return None
    with db.connect() as conn:
        original = conn.execute(
            "SELECT retrieved FROM query_log WHERE group_id = %s AND answer = %s ORDER BY id DESC LIMIT 1",
            (q.group_id, quoted["body"]),
        ).fetchone()
    related = (original["retrieved"] or {}).get("facts", []) if original else []
    facts.correct(q.group_id, statement, q.sender_jid, q.wa_msg_id, quoted["ts"], related)
    observe.count("ask_total", outcome="correction")
    log_question(q, q.group_id, [], {}, statement, None, (None, None), None, None, "correction")
    return {"answer": group["settings"]["correction_ack"], "quote": None}


def answer_in(q, group, cite_group=False):
    """Answer a question from one group. Returns the response dict."""
    s = group["settings"]
    t0 = time.perf_counter()
    chunks, timings = retrieval.search(group["external_id"], q.question)
    confidence = chunks[0]["score"] if chunks else 0.0
    text, quote, tokens, cost, provider = s["refusal_text"], None, (None, None), None, None
    outcome, fact_ids = "refused", []
    if confidence >= s["confidence_threshold"]:
        global_settings = groups.global_settings()
        provider = providers.resolve(group, global_settings)
        if provider is None:
            text, outcome = NO_PROVIDER, "no_provider"
        elif budget.exceeded(group, global_settings):
            text, outcome = budget.BUDGET_TEXT, "budget"
        else:
            t = time.perf_counter()
            fact_rows = facts.search(group["external_id"], q.question) if s["decision_tracking"] else []
            timings["facts_ms"] = round((time.perf_counter() - t) * 1000)
            fact_ids = [r["id"] for r in fact_rows]
            t = time.perf_counter()
            text, *tokens = answer.generate(q.question, chunks, provider, s, fact_rows)
            timings["llm_ms"] = round((time.perf_counter() - t) * 1000)
            cost = providers.cost(provider, *tokens)
            if answer.is_refusal(text):
                text = s["refusal_text"]
            else:
                text, quote = _cite(text, _source(chunks[0]), group["name"] if cite_group else None)
                outcome = "answered" if not cite_group else "dm"
    timings["total_ms"] = round((time.perf_counter() - t0) * 1000)
    observe.count("ask_total", outcome=outcome)
    observe.observe_latency(timings["total_ms"] / 1000)
    log_question(
        q,
        group["external_id"],
        chunks,
        timings,
        text,
        confidence,
        tuple(tokens),
        provider,
        cost,
        outcome,
        fact_ids,
    )
    return {"answer": text, "quote": quote, "confidence": confidence}


def answer_privately(q):
    """Pick the member's group that matches the question best and answer from
    it with a text citation. Private questions are never stored as messages."""
    candidates = groups.dm_candidates(q.sender_jid, gateway_state.members())
    if not candidates:
        observe.count("ask_total", outcome="dm_unknown")
        return {"answer": NO_DM_GROUP, "quote": None}
    best, best_score = None, -1.0
    for g in candidates[:5]:
        hits, _ = retrieval.search(g["external_id"], q.question)
        score = hits[0]["score"] if hits else 0.0
        if score > best_score:
            best, best_score = g, score
    return answer_in(q, best, cite_group=True)
