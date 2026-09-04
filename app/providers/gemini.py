import base64

from . import http

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _headers(provider):
    return {"x-goog-api-key": provider["api_key"]}


def models(provider):
    data = http.get(BASE, _headers(provider), {"pageSize": 200})
    return [
        m["name"].removeprefix("models/")
        for m in data.get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]


def describe_image(provider, image, mime, prompt):
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": mime, "data": base64.b64encode(image).decode()}},
                    {"text": prompt},
                ],
            }
        ],
        "generationConfig": {"maxOutputTokens": 2048},
    }
    data = http.post(f"{BASE}/{provider['model']}:generateContent", _headers(provider), body)
    parts = data["candidates"][0]["content"].get("parts", [])
    return "".join(p.get("text", "") for p in parts).strip()


def generate(provider, system, prompt):
    body = http.merge(
        {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
        },
        provider["options"],
    )
    data = http.post(f"{BASE}/{provider['model']}:generateContent", _headers(provider), body)
    parts = data["candidates"][0]["content"].get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    usage = data.get("usageMetadata", {})
    return text, usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
