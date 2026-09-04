import base64

from . import http

URL = "https://api.anthropic.com/v1/messages"
MODELS_URL = "https://api.anthropic.com/v1/models"


def _headers(provider):
    return {"x-api-key": provider["api_key"], "anthropic-version": "2023-06-01"}


def models(provider):
    data = http.get(MODELS_URL, _headers(provider), {"limit": 100})
    return [m["id"] for m in data.get("data", [])]


def describe_image(provider, image, mime, prompt):
    body = {
        "model": provider["model"],
        "max_tokens": 2048,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": base64.b64encode(image).decode(),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    data = http.post(URL, _headers(provider), body)
    return "".join(b["text"] for b in data["content"] if b["type"] == "text").strip()


def generate(provider, system, prompt):
    body = http.merge(
        {
            "model": provider["model"],
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        },
        provider["options"],
    )
    data = http.post(URL, _headers(provider), body)
    text = "".join(b["text"] for b in data["content"] if b["type"] == "text").strip()
    usage = data.get("usage", {})
    return text, usage.get("input_tokens"), usage.get("output_tokens")
