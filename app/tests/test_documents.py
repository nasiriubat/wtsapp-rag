import io
import uuid

import pytest
from conftest import needs_db

pytestmark = needs_db

TEXT = b"# Cabin rules\n\nThe sauna is heated on Fridays.\n\nQuiet hours start at 22:00.\n"


def test_a_markdown_file_becomes_labelled_parts():
    from documents.read import read

    parts = read("rules.md", "text/markdown", TEXT)
    assert len(parts) == 1
    label, text = parts[0]
    assert label == "rules.md" and "sauna is heated on Fridays" in text


def test_a_spreadsheet_becomes_text():
    openpyxl = pytest.importorskip("openpyxl")
    from documents.read import read

    book = openpyxl.Workbook()
    book.active.append(["Item", "Price"])
    book.active.append(["Firewood", 45])
    buffer = io.BytesIO()
    book.save(buffer)

    parts = read("prices.xlsx", None, buffer.getvalue())
    assert "Firewood" in parts[0][1] and "45" in parts[0][1]


def test_an_empty_or_unreadable_file_says_why():
    from documents.read import Unreadable, read

    with pytest.raises(Unreadable, match="empty"):
        read("nothing.txt", "text/plain", b"")
    with pytest.raises(Unreadable, match="image"):
        read("photo.png", "image/png", b"\x89PNG not really", provider=None)


def test_long_text_is_sliced_into_parts_of_a_chunk_size():
    from documents.read import MAX_CHARS, _slice

    parts = _slice("\n\n".join(["word " * 200] * 5), "big.txt")
    assert len(parts) > 1 and all(len(text) <= MAX_CHARS for _, text in parts)


def test_upload_indexes_and_is_searchable_by_every_group(browser, stub_embeddings):
    import db
    import documents

    res = browser.post(
        "/admin/documents",
        data={"csrf": browser.csrf, "group_id": ""},
        files={"files": ("rules.md", TEXT, "text/markdown")},
        follow_redirects=False,
    )
    assert res.status_code == 303
    document_id = documents.list_all()[0]["id"]
    documents.index_pending()

    row = documents.get(document_id)
    assert row["status"] == "indexed" and row["parts"] == 1
    with db.connect() as conn:
        chunk = conn.execute(
            "SELECT group_id, source_label, content, first_msg_id FROM chunks WHERE document_id = %s",
            (document_id,),
        ).fetchone()
        # A shared document has no group and no message behind it, and its label
        # is inside the text so the model knows what it is reading.
        assert chunk["group_id"] is None and chunk["first_msg_id"] is None
        assert chunk["source_label"] == "rules.md" and chunk["content"].startswith("rules.md\n")
        # The bytes are dropped once the text is out.
        assert (
            conn.execute("SELECT raw FROM documents WHERE id = %s", (document_id,)).fetchone()["raw"] is None
        )

    documents.delete(document_id)
    with db.connect() as conn:
        assert not conn.execute("SELECT 1 FROM chunks WHERE document_id = %s", (document_id,)).fetchall()


def test_the_same_file_uploaded_twice_stays_one_document(browser):
    import documents

    first = documents.create(None, "rules.md", "text/markdown", TEXT)
    second = documents.create(None, "rules.md", "text/markdown", TEXT)
    assert first == second
    documents.delete(first)


def test_an_unreadable_upload_is_recorded_with_its_reason(stub_embeddings):
    import documents

    document_id = documents.create(None, f"broken-{uuid.uuid4()}.png", "image/png", b"not an image")
    documents.index_pending()
    row = documents.get(document_id)
    assert row["status"] == "failed" and "model" in row["error"]
    documents.delete(document_id)


def test_a_document_answer_cites_the_file_not_a_message():
    import answer

    chunk = {"document_id": 7, "source_label": "rules.pdf, page 2", "content": "rules.pdf, page 2\nSauna"}
    assert answer.is_document(chunk)
    prompt = answer.build_prompt("when is the sauna?", [chunk])
    assert "<document>" in prompt and "<chat>" not in prompt


def test_group_documents_are_only_searched_by_that_group(stub_embeddings):
    import db
    import documents
    import groups

    gid = f"test-{uuid.uuid4()}@g.us"
    group = groups.create("whatsapp", gid, "Cabin")
    document_id = documents.create(gid, "cabin.md", "text/markdown", TEXT)
    documents.index_pending()
    with db.connect() as conn:
        assert (
            conn.execute("SELECT group_id FROM chunks WHERE document_id = %s", (document_id,)).fetchone()[
                "group_id"
            ]
            == gid
        )
    documents.delete(document_id)
    groups.delete(group["id"])


def test_a_file_shared_in_a_chat_is_indexed_only_when_the_group_asked_for_it(client, stub_embeddings):
    import base64
    import uuid as _uuid

    from conftest import GW

    import documents
    import groups

    gid = f"share-{_uuid.uuid4()}@g.us"
    group = groups.create("whatsapp", gid, "Cabin")
    body = {
        "group_id": gid,
        "sender_jid": "a@s.whatsapp.net",
        "filename": "rules.md",
        "mime": "text/markdown",
        "data": base64.b64encode(TEXT).decode(),
    }

    # index_files defaults to off: downloading media is opt-in.
    assert client.post("/ingest/file", json=body, headers=GW).json() == {"ok": True, "stored": False}

    groups.apply(group["id"], settings={**group["settings"], "index_files": True})
    assert client.post("/ingest/file", json=body, headers=GW).json() == {"ok": True, "stored": True}
    stored = [d for d in documents.list_all() if d["group_id"] == gid]
    assert len(stored) == 1 and stored[0]["filename"] == "rules.md"

    # An opted-out member's file is not kept either.
    opted_out = {**group["settings"], "index_files": True, "opt_out": ["a@s.whatsapp.net"]}
    groups.apply(group["id"], settings=opted_out)
    body["filename"] = "second.md"
    assert client.post("/ingest/file", json=body, headers=GW).json() == {"ok": True, "stored": False}

    junk = {**body, "data": "not base64!", "sender_jid": "b@s.whatsapp.net"}
    assert client.post("/ingest/file", json=junk, headers=GW).status_code == 422

    documents.delete(stored[0]["id"])
    groups.delete(group["id"])


def test_a_damaged_pdf_is_marked_failed_not_crashed(stub_embeddings):
    import documents

    document_id = documents.create(
        None, f"broken-{uuid.uuid4()}.pdf", "application/pdf", b"%PDF-1.4 garbage" * 40
    )
    documents.index_pending()
    row = documents.get(document_id)
    assert row["status"] == "failed" and "PDF" in row["error"]
    documents.delete(document_id)


def test_a_parser_bug_quarantines_the_document_instead_of_the_process(stub_embeddings, monkeypatch):
    import documents

    def explode(*a, **kw):
        raise TypeError("a bug in our own code, not the file")

    monkeypatch.setattr(documents, "read", explode)
    document_id = documents.create(None, f"bug-{uuid.uuid4()}.md", "text/markdown", TEXT)
    documents.index_pending()  # must return, not raise
    row = documents.get(document_id)
    assert row["status"] == "failed" and "log" in row["error"]
    # Marked, so the next tick does not meet it again.
    monkeypatch.setattr(documents, "read", lambda *a, **kw: pytest.fail("re-read a quarantined document"))
    documents.index_pending()
    documents.delete(document_id)


def test_what_comes_out_of_a_file_is_capped_whatever_went_in():
    from documents.read import MAX_PARTS, MAX_TEXT, Unreadable, _bounded

    _bounded([("a", "x" * 100)])
    with pytest.raises(Unreadable, match="Split it up"):
        _bounded([("a", "x")] * (MAX_PARTS + 1))
    with pytest.raises(Unreadable, match="Split it up"):
        _bounded([("a", "x" * (MAX_TEXT + 1))])
