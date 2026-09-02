from . import http

URL = "https://api.anthropic.com/v1/messages"


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
    data = http.post(
        URL,
        {"x-api-key": provider["api_key"], "anthropic-version": "2023-06-01"},
        body,
    )
    text = "".join(b["text"] for b in data["content"] if b["type"] == "text").strip()
    usage = data.get("usage", {})
    return text, usage.get("input_tokens"), usage.get("output_tokens")
