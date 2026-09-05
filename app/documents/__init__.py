"""Documents the admin uploads. They are chunked into the same table as the
chat, so one search covers both; a document chunk carries a label instead of a
message id, and the answer cites the label."""

import hashlib
import json
import logging
import re

import psycopg

import db
import embed
import groups
import providers

from .read import MAX_BYTES, Unreadable, read

__all__ = ["MAX_BYTES", "Unreadable", "create", "delete", "get", "index_pending", "list_all", "reindex"]

log = logging.getLogger(__name__)

BATCH = 3  # documents per pass; a scanned one can take a minute of model calls

_COLUMNS = "id, group_id, filename, mime, bytes, sha256, status, error, parts, uploaded_at"


def list_all():
    with db.connect() as conn:
        return conn.execute(
            "SELECT d.id, d.group_id, d.filename, d.mime, d.bytes, d.status, d.error, d.parts, "
            "d.uploaded_at, g.name AS group_name "
            "FROM documents d LEFT JOIN groups g ON g.external_id = d.group_id "
            "ORDER BY d.id DESC"
        ).fetchall()


def get(document_id):
    with db.connect() as conn:
        return conn.execute(f"SELECT {_COLUMNS} FROM documents WHERE id = %s", (document_id,)).fetchone()


def clean_name(filename):
    """A file name ends up in the prompt and in the reply sent to the chat, and
    a member choosing it must not get structure or control characters through."""
    name = re.sub(r"[\x00-\x1f\x7f<>]", "", filename or "").strip()
    name = re.sub(r"\s+", " ", name)
    return name[:120] or "file"


def create(group_id, filename, mime, data):
    """Store an upload for the loop to read. Re-uploading the same file into the
    same place resets that document instead of making a second one."""
    filename = clean_name(filename)
    if not data:
        raise Unreadable("the file is empty")
    if len(data) > MAX_BYTES:
        raise Unreadable(f"the file is larger than {MAX_BYTES // 1024 // 1024} MB")
    digest = hashlib.sha256(data).hexdigest()
    with db.connect() as conn, conn.transaction():
        existing = conn.execute(
            "SELECT id FROM documents WHERE coalesce(group_id, '') = coalesce(%s, '') AND sha256 = %s",
            (group_id, digest),
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM chunks WHERE document_id = %s", (existing["id"],))
            conn.execute(
                "UPDATE documents SET raw = %s, filename = %s, mime = %s, bytes = %s, "
                "status = 'pending', error = NULL, content = NULL, parts = 0, uploaded_at = now() "
                "WHERE id = %s",
                (data, filename, mime, len(data), existing["id"]),
            )
            return existing["id"]
        return conn.execute(
            "INSERT INTO documents (group_id, filename, mime, bytes, sha256, raw) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (group_id, filename, mime, len(data), digest, data),
        ).fetchone()["id"]


def delete(document_id):
    with db.connect() as conn:
        conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))


def reindex(document_id):
    """Re-embed from the text already extracted. For after a model change."""
    with db.connect() as conn, conn.transaction():
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
        conn.execute(
            "UPDATE documents SET status = 'pending', error = NULL, parts = 0 WHERE id = %s", (document_id,)
        )


def _provider(group_id):
    """The model that reads images for this document: the group's own, or the
    global default for a shared one."""
    settings = groups.global_settings()
    group = groups.get(group_id) if group_id else None
    if group is not None:
        return providers.resolve(group, settings)
    default = settings["default_provider_id"]
    provider = providers.get(default) if default else None
    return provider if provider and provider["enabled"] else None


def _store(document_id, group_id, parts):
    # The label lives inside the chunk text as well as beside it: metadata does
    # not reach the model's context, and the model needs to know what it is reading.
    contents = [f"{label}\n{text}" for label, text in parts]
    vectors = embed.passages(contents)
    with db.connect() as conn, conn.transaction():
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
        for (label, _), content, vector in zip(parts, contents, vectors, strict=True):
            conn.execute(
                "INSERT INTO chunks (group_id, content, document_id, source_label, embedding) "
                "VALUES (%s, %s, %s, %s, %s::vector)",
                (group_id, content, document_id, label, embed.literal(vector)),
            )
        conn.execute(
            "UPDATE documents SET status = 'indexed', error = NULL, parts = %s, raw = NULL, "
            "content = %s WHERE id = %s",
            (len(parts), json.dumps(parts), document_id),
        )


def _fail(document_id, message):
    with db.connect() as conn:
        conn.execute(
            "UPDATE documents SET status = 'failed', error = %s WHERE id = %s", (message, document_id)
        )


def _index(row):
    try:
        if row["content"]:
            parts = [tuple(part) for part in row["content"]]  # a re-index: already extracted
        else:
            parts = read(row["filename"], row["mime"], bytes(row["raw"] or b""), _provider(row["group_id"]))
        _store(row["id"], row["group_id"], parts)
    except Unreadable as e:
        _fail(row["id"], str(e))
        log.info("document unreadable", extra={"document": row["id"], "reason": str(e)})
        return
    except psycopg.Error:
        # The database, not the document. Leave it pending; the loop backs off.
        raise
    except Exception:
        # A parser or model bug on this one file. Quarantine the row so the loop
        # does not meet the same file again on every tick; the log has the trace.
        log.exception("document indexing crashed", extra={"document": row["id"]})
        _fail(row["id"], "could not be read; the server log has the details")
        return
    log.info("document indexed", extra={"document": row["id"], "parts": len(parts)})


def index_pending():
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, group_id, filename, mime, raw, content FROM documents "
            "WHERE status = 'pending' ORDER BY id LIMIT %s",
            (BATCH,),
        ).fetchall()
    for row in rows:
        _index(row)
