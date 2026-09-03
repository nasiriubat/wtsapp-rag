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
