from . import http

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def generate(provider, system, prompt):
    body = http.merge(
        {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
        },
        provider["options"],
    )
    data = http.post(
        f"{BASE}/{provider['model']}:generateContent",
        {"x-goog-api-key": provider["api_key"]},
        body,
    )
    parts = data["candidates"][0]["content"].get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    usage = data.get("usageMetadata", {})
    return text, usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
