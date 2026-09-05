"""Pictures and scanned pages go to the model; this is that path with the
model faked, and the cap on how many pages it will read."""

import io

import pytest


def blank_pdf(pages):
    """A minimal PDF with N empty pages: no text layer, so it reads as scanned."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>")
    for _ in range(pages):
        objs.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>")
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


@pytest.fixture()
def vision(monkeypatch):
    import providers

    seen = []

    def describe(provider, image, mime, prompt):
        seen.append((mime, len(image)))
        return f"Transcribed page {len(seen)}: sauna rota, week 41 Mikko."

    monkeypatch.setattr(providers, "describe_image", describe)
    return seen


def test_a_picture_is_read_by_the_model_and_labelled_with_its_name(vision):
    from documents.read import read

    provider = {"kind": "gemini", "api_key": "k", "model": "m"}
    parts = read("rota.png", "image/png", b"\x89PNG fake", provider)
    assert parts == [("rota.png", "Transcribed page 1: sauna rota, week 41 Mikko.")]
    assert vision == [("image/png", 9)]


def test_a_scanned_pdf_is_read_page_by_page(vision):
    from documents.read import read

    provider = {"kind": "gemini", "api_key": "k", "model": "m"}
    parts = read("scan.pdf", "application/pdf", blank_pdf(2), provider)
    assert [label for label, _ in parts] == ["scan.pdf, page 1", "scan.pdf, page 2"]
    assert all(mime == "image/png" and size > 100 for mime, size in vision)


def test_a_long_scanned_pdf_is_refused_before_it_costs_anything(vision):
    from documents.read import VISION_PAGES, Unreadable, read

    with pytest.raises(Unreadable, match="Split it up"):
        read("scan.pdf", "application/pdf", blank_pdf(VISION_PAGES + 1), {"kind": "gemini"})
    assert vision == []


def test_a_scanned_pdf_without_a_provider_says_what_it_needs():
    from documents.read import Unreadable, read

    with pytest.raises(Unreadable, match="needs a model"):
        read("scan.pdf", "application/pdf", blank_pdf(1), None)


def test_a_spreadsheet_is_read_sheet_by_sheet():
    import openpyxl

    from documents.read import read

    book = openpyxl.Workbook()
    book.active.title = "Prices"
    book.active.append(["Item", "Price"])
    book.active.append(["Firewood", 45])
    book.create_sheet("Notes").append(["Bring cash"])
    buffer = io.BytesIO()
    book.save(buffer)
    parts = read("prices.xlsx", None, buffer.getvalue())
    assert [label for label, _ in parts] == ["prices.xlsx, sheet Prices", "prices.xlsx, sheet Notes"]
    assert "Firewood | 45" in parts[0][1] and "Bring cash" in parts[1][1]
