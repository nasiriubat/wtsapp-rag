"""OpenAI chat-completions wire format. Covers OpenAI, OpenRouter, a LiteLLM
proxy, Groq, Mistral, Together, Ollama and anything else that speaks it."""

import base64

from . import http

DEFAULT_BASE = "https://api.openai.com/v1"


def _base(provider):
    return (provider["base_url"] or DEFAULT_BASE).rstrip("/")


def _headers(provider):
    return {"authorization": f"Bearer {provider['api_key']}"}


def _limit(base, tokens=1024):
    # OpenAI itself retired max_tokens for its newer models; everyone else who
    # speaks this format still expects it. Sampling parameters are left at the
    # provider's defaults because several current models reject them outright.
    return {"max_completion_tokens": tokens} if base == DEFAULT_BASE else {"max_tokens": tokens}


def models(provider):
    data = http.get(f"{_base(provider)}/models", _headers(provider))
    return sorted(m["id"] for m in data.get("data", []) if m.get("id"))


def describe_image(provider, image, mime, prompt):
    base = _base(provider)
    url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
    body = {
        "model": provider["model"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ],
        **_limit(base, 2048),
    }
    data = http.post(f"{base}/chat/completions", _headers(provider), body)
    return (data["choices"][0]["message"]["content"] or "").strip()


def generate(provider, system, prompt):
    base = _base(provider)
    limit = _limit(base)
    body = http.merge(
        {
            "model": provider["model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            **limit,
        },
        provider["options"],
    )
    data = http.post(f"{base}/chat/completions", _headers(provider), body)
    text = (data["choices"][0]["message"]["content"] or "").strip()
    usage = data.get("usage") or {}
    return text, usage.get("prompt_tokens"), usage.get("completion_tokens")
