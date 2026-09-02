import json
import os
import urllib.request
from datetime import date

MODEL = "gemini-3.8-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

SYSTEM = """You answer questions about a WhatsApp group's chat history.
Use only the excerpts you are given. If they do not contain the answer, reply exactly:
I don't have anything on that.
Answer in the language of the question. Be brief: one to three sentences.
Give the date when it matters, for example when something was decided or later changed.
Do not mention excerpts or context; just answer."""


def _format(chunks):
    return "\n\n".join(
        f"[{c['start_ts']:%d %b %Y %H:%M} to {c['end_ts']:%H:%M}]\n{c['content']}" for c in chunks
    )


def generate(question, chunks):
    prompt = f"Today is {date.today():%d %b %Y}.\n\nExcerpts:\n\n{_format(chunks)}\n\nQuestion: {question}"
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        data = json.load(res)
    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    usage = data.get("usageMetadata", {})
    return text, usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
