"""OpenAI chat-completions wire format. Covers OpenAI, OpenRouter, a LiteLLM
proxy, Groq, Mistral, Together, Ollama and anything else that speaks it."""

from . import http

DEFAULT_BASE = "https://api.openai.com/v1"


def generate(provider, system, prompt):
    base = (provider["base_url"] or DEFAULT_BASE).rstrip("/")
    # OpenAI itself retired max_tokens for its newer models; everyone else who
    # speaks this format still expects it. Sampling parameters are left at the
    # provider's defaults because several current models reject them outright.
    limit = {"max_completion_tokens": 1024} if base == DEFAULT_BASE else {"max_tokens": 1024}
    body = http.merge(
        {
            "model": provider["model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            **limit,
        },
        provider["options"],
    )
    data = http.post(f"{base}/chat/completions", {"authorization": f"Bearer {provider['api_key']}"}, body)
    text = (data["choices"][0]["message"]["content"] or "").strip()
    usage = data.get("usage") or {}
    return text, usage.get("prompt_tokens"), usage.get("completion_tokens")
