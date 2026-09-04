import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import admin
import admin_api
import audit
import groups
import providers

pages = APIRouter()
actions = APIRouter()

KIND_HELP = {
    "anthropic": "Anthropic. Model e.g. claude-opus-5 or claude-sonnet-5.",
    "gemini": "Google Gemini. Model e.g. gemini-3.8-flash.",
    "openai": "OpenAI-compatible: OpenAI, OpenRouter, LiteLLM proxy, Groq, Mistral, Together, Ollama. "
    "Set the base URL for anything but api.openai.com.",
}


def _options(raw):
    try:
        value = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"options is not valid JSON: {e}") from e
    if not isinstance(value, dict):
        raise HTTPException(422, "options must be a JSON object")
    return value


@pages.get("/providers", response_class=HTMLResponse)
def page(request: Request, message: str | None = None):
    return admin.render(
        request,
        "providers.html",
        providers=providers.list_all(),
        default_id=groups.global_settings()["default_provider_id"],
        kinds={k: KIND_HELP.get(k, "") for k in providers.KINDS},
        message=message,
    )


@actions.post("/providers")
def create(
    name: str = Form(),
    kind: str = Form(),
    api_key: str = Form(),
    model: str = Form(),
    base_url: str = Form(""),
    price_in: float = Form(0),
    price_out: float = Form(0),
    options: str = Form(""),
):
    fields = {
        "name": name,
        "kind": kind,
        "api_key": api_key,
        "model": model,
        "base_url": base_url or None,
        "price_in": price_in,
        "price_out": price_out,
        "options": _options(options),
    }
    admin_api.add_provider(fields)
    return RedirectResponse("/admin/providers", status_code=303)


@actions.post("/providers/{provider_id}")
def update(
    provider_id: int,
    name: str = Form(),
    model: str = Form(),
    base_url: str = Form(""),
    price_in: float = Form(0),
    price_out: float = Form(0),
    options: str = Form(""),
    enabled: bool = Form(False),
    api_key: str = Form(""),
):
    fields = {
        "name": name,
        "model": model,
        "base_url": base_url or None,
        "price_in": price_in,
        "price_out": price_out,
        "options": _options(options),
        "enabled": enabled,
    }
    if api_key:
        fields["api_key"] = api_key
    admin_api.apply_provider(provider_id, fields)
    return RedirectResponse("/admin/providers", status_code=303)


@actions.post("/providers/{provider_id}/delete")
def delete(provider_id: int):
    providers.delete(provider_id)
    audit.log("provider.delete", str(provider_id))
    return RedirectResponse("/admin/providers", status_code=303)


@actions.post("/providers/{provider_id}/default")
def make_default(provider_id: int):
    if providers.get(provider_id) is None:
        raise HTTPException(404)
    groups.set_global(default_provider_id=provider_id)
    audit.log("settings.update", "global", {"default_provider_id": provider_id})
    return RedirectResponse("/admin/providers", status_code=303)


@actions.post("/providers/{provider_id}/test", response_class=HTMLResponse)
def test(provider_id: int):
    try:
        reply = admin_api.run_provider_test(provider_id)
    except HTTPException as e:
        return HTMLResponse(f'<span class="bad">Failed: {admin.escape(str(e.detail))}</span>')
    return HTMLResponse(f'<span class="ok">OK, replied "{admin.escape(reply[:60])}"</span>')
