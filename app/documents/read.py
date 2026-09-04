"""An uploaded file becomes a list of (label, text) parts, ready to embed.

MarkItDown covers the office and text formats. Images and scanned pages carry no
text to extract, so they go to the group's own vision model instead: cheaper than
shipping an OCR engine, and it reads diagrams and handwriting, which OCR does not.
"""

import io
import logging
import pathlib
import re

import pdfplumber
from markitdown import MarkItDown, StreamInfo

import providers

log = logging.getLogger(__name__)

MAX_BYTES = 25 * 1024 * 1024
MAX_CHARS = 1600  # the size of a chat episode, so the two score comparably
VISION_PAGES = 20  # a scanned page costs one model call, so cap the bill
TEXT_PER_PAGE = 80  # below this a PDF page has no text layer worth keeping

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".tiff"}

PROMPT = (
    "Transcribe this page for a search index. Write out every word you can read, "
    "including tables and handwriting, then describe any diagram or photograph in "
    "one sentence. Add nothing that is not there."
)


class Unreadable(Exception):
    """The file cannot be turned into text. The message is shown to the admin."""


def _markitdown():
    # No plugins: a converter installed elsewhere on the machine is not something
    # an upload should be able to reach.
    return MarkItDown(enable_plugins=False)


def _slice(text, label):
    """Paragraph-aligned pieces of at most MAX_CHARS."""
    out, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if current and len(current) + len(para) > MAX_CHARS:
            out.append(current)
            current = ""
        while len(para) > MAX_CHARS:
            out.append(para[:MAX_CHARS])
            para = para[MAX_CHARS:]
        current = f"{current}\n\n{para}" if current else para
    if current:
        out.append(current)
    return [(label, piece) for piece in out]


def _numbered(parts):
    if len(parts) <= 1:
        return parts
    return [(f"{label}, part {i}", text) for i, (label, text) in enumerate(parts, 1)]


def _describe(provider, data, mime):
    if provider is None:
        raise Unreadable("reading an image needs a model. Add a provider first.")
    try:
        text = providers.describe_image(provider, data, mime, PROMPT)
    except Exception as e:  # every provider failure reads the same to the admin
        raise Unreadable(f"the model could not read it: {e}") from e
    if not text.strip():
        raise Unreadable("the model found nothing readable in it")
    return text.strip()


def _pdf(filename, data, provider):
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [(page, (page.extract_text() or "").strip()) for page in pdf.pages]
        if not pages:
            raise Unreadable("this PDF has no pages")
        if all(len(text) < TEXT_PER_PAGE for _, text in pages):
            return _scanned(filename, pages, provider)
        parts = []
        for number, (_, text) in enumerate(pages, 1):
            if text:
                parts += _slice(text, f"{filename}, page {number}")
    if not parts:
        raise Unreadable("no text could be extracted from this PDF")
    return parts


def _scanned(filename, pages, provider):
    if len(pages) > VISION_PAGES:
        raise Unreadable(
            f"this PDF has no text layer, so the model has to read it as {len(pages)} images, "
            f"and it reads at most {VISION_PAGES} at a time. Split it up."
        )
    parts = []
    for number, (page, _) in enumerate(pages, 1):
        buffer = io.BytesIO()
        page.to_image(resolution=150).save(buffer, format="PNG")
        parts.append((f"{filename}, page {number}", _describe(provider, buffer.getvalue(), "image/png")))
    log.info("read a scanned pdf", extra={"file": filename, "pages": len(parts)})
    return parts


def read(filename, mime, data, provider=None):
    """Parts of (label, text). Raises Unreadable with a sentence for the admin."""
    if not data:
        raise Unreadable("the file is empty")
    if len(data) > MAX_BYTES:
        raise Unreadable(f"the file is larger than {MAX_BYTES // 1024 // 1024} MB")
    extension = pathlib.Path(filename).suffix.lower()

    if (mime or "").startswith("image/") or extension in IMAGE_EXTENSIONS:
        return [(filename, _describe(provider, data, mime or "image/png"))]
    if extension == ".pdf" or mime == "application/pdf":
        return _pdf(filename, data, provider)

    try:
        result = _markitdown().convert_stream(
            io.BytesIO(data),
            stream_info=StreamInfo(extension=extension or None, mimetype=mime or None, filename=filename),
        )
    except Exception as e:
        raise Unreadable(f"this file could not be read: {e}") from e
    text = (result.markdown or "").strip()
    if not text:
        raise Unreadable("no text could be extracted from this file")
    return _numbered(_slice(text, filename))
