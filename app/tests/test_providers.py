from decimal import Decimal

import httpx
import pytest

import providers
from providers import http


def provider(kind, **over):
    base = {
        "id": 1,
        "kind": kind,
        "api_key": "k",
        "model": "m",
        "base_url": None,
        "options": {},
        "price_in": 1.5,
        "price_out": 6,
        "enabled": True,
    }
    return {**base, **over}


def test_anthropic_request_and_response(httpx_mock):
    httpx_mock.add_response(
        url=providers.anthropic.URL,
        json={
            "content": [{"type": "text", "text": "Hi "}],
            "usage": {"input_tokens": 10, "output_tokens": 2},
        },
    )
    out = providers.generate(provider("anthropic", options={"output_config": {"effort": "low"}}), "sys", "q")
    assert out == ("Hi", 10, 2)
    req = httpx_mock.get_request()
    assert req.headers["x-api-key"] == "k"
    body = req.read()
    assert b'"effort": "low"' in body or b'"effort":"low"' in body
    assert b"temperature" not in body


def test_gemini_thinking_budget_option_merges_into_generation_config(httpx_mock):
    httpx_mock.add_response(
        json={
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1},
        }
    )
    p = provider(
        "gemini", model="gemini-x", options={"generationConfig": {"thinkingConfig": {"thinkingBudget": 0}}}
    )
    assert providers.generate(p, "sys", "q") == ("ok", 5, 1)
    req = httpx_mock.get_request()
    assert str(req.url).endswith("/gemini-x:generateContent")
    assert req.headers["x-goog-api-key"] == "k"
    assert b"thinkingBudget" in req.read()
    assert b"maxOutputTokens" in req.read()


def test_openai_compat_uses_base_url_and_bearer(httpx_mock):
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        json={
            "choices": [{"message": {"content": " yes"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        },
    )
    p = provider("openai", base_url="https://openrouter.ai/api/v1/", options={"temperature": 0.2})
    assert providers.generate(p, "sys", "q") == ("yes", 3, 1)
    req = httpx_mock.get_request()
    assert req.headers["authorization"] == "Bearer k"
    assert b'"max_tokens"' in req.read() and b'"temperature"' in req.read()


def test_official_openai_uses_max_completion_tokens(httpx_mock):
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "ok"}}], "usage": {}},
    )
    providers.generate(provider("openai"), "sys", "q")
    body = httpx_mock.get_request().read()
    assert b"max_completion_tokens" in body and b'"max_tokens"' not in body


def test_retries_once_on_5xx_then_succeeds(httpx_mock):
    httpx_mock.add_response(status_code=503)
    httpx_mock.add_response(json={"choices": [{"message": {"content": "ok"}}], "usage": {}})
    assert providers.generate(provider("openai"), "s", "q") == ("ok", None, None)
    assert len(httpx_mock.get_requests()) == 2


def test_4xx_is_final(httpx_mock):
    httpx_mock.add_response(status_code=401)
    with pytest.raises(httpx.HTTPStatusError):
        providers.generate(provider("openai"), "s", "q")
    assert len(httpx_mock.get_requests()) == 1


def test_merge_removes_null_and_merges_nested():
    body = {"a": 1, "cfg": {"x": 1, "y": 2}}
    assert http.merge(body, {"a": None, "cfg": {"y": 3}, "z": 9}) == {"cfg": {"x": 1, "y": 3}, "z": 9}


def test_cost_per_million_tokens():
    assert providers.cost(provider("openai"), 1_000_000, 100_000) == Decimal("2.1")


def test_the_model_list_comes_from_each_provider(monkeypatch):
    import providers
    from providers import http

    calls = {}

    def fake_get(url, headers, params=None):
        calls["url"] = url
        if "anthropic" in url:
            return {"data": [{"id": "claude-opus-5"}]}
        if "generativelanguage" in url:
            return {
                "models": [
                    {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
                ]
            }
        return {"data": [{"id": "gpt-5.4-mini"}, {"id": "gpt-5.4"}]}

    monkeypatch.setattr(http, "get", fake_get)
    assert providers.models({"kind": "anthropic", "api_key": "k"}) == ["claude-opus-5"]
    # Only the models that can answer, and without the "models/" prefix.
    assert providers.models({"kind": "gemini", "api_key": "k"}) == ["gemini-3.8-flash"]
    assert providers.models({"kind": "openai", "api_key": "k", "base_url": "https://x/v1"}) == [
        "gpt-5.4",
        "gpt-5.4-mini",
    ]
    assert calls["url"] == "https://x/v1/models"


def test_an_image_is_sent_in_each_wire_format(monkeypatch):
    import providers
    from providers import http

    sent = {}

    def fake_post(url, headers, body):
        sent["body"] = body
        return {
            "content": [{"type": "text", "text": "a sauna"}],
            "candidates": [{"content": {"parts": [{"text": "a sauna"}]}}],
            "choices": [{"message": {"content": "a sauna"}}],
        }

    monkeypatch.setattr(http, "post", fake_post)
    for kind in ("anthropic", "gemini", "openai"):
        provider = {"kind": kind, "api_key": "k", "model": "m", "base_url": None, "options": {}}
        assert providers.describe_image(provider, b"png-bytes", "image/png", "read it") == "a sauna"
    # The last one through is the OpenAI shape: a data URI, not raw bytes.
    assert sent["body"]["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_a_missing_default_provider_is_adopted_not_left_broken(monkeypatch):
    import bootstrap
    import groups
    import providers

    rows = [{"id": 7, "name": "Claude", "enabled": False}, {"id": 9, "name": "Gemini", "enabled": True}]
    chosen = {}
    monkeypatch.setattr(providers, "list_all", lambda: rows)
    monkeypatch.setattr(providers, "get", lambda i: next((r for r in rows if r["id"] == i), None))
    monkeypatch.setattr(groups, "set_global", lambda **kw: chosen.update(kw))

    # Nothing set: the first enabled provider is adopted.
    monkeypatch.setattr(groups, "global_settings", lambda: {"default_provider_id": None})
    assert bootstrap.ensure_default()["id"] == 9 and chosen == {"default_provider_id": 9}

    # Pointing at a deleted row: same repair, rather than refusing every question.
    chosen.clear()
    monkeypatch.setattr(groups, "global_settings", lambda: {"default_provider_id": 404})
    assert bootstrap.ensure_default()["id"] == 9

    # Pointing at a disabled row: also repaired.
    chosen.clear()
    monkeypatch.setattr(groups, "global_settings", lambda: {"default_provider_id": 7})
    assert bootstrap.ensure_default()["id"] == 9

    # A healthy default is left alone.
    chosen.clear()
    monkeypatch.setattr(groups, "global_settings", lambda: {"default_provider_id": 9})
    assert bootstrap.ensure_default()["id"] == 9 and chosen == {}
