import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

import admin
import admin_api
import audit
import db
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
def page(request: Request):
    with db.connect() as conn:
        answered = {
            r["provider_id"]: r["n"]
            for r in conn.execute(
                "SELECT provider_id, count(*) AS n FROM query_log "
                "WHERE provider_id IS NOT NULL GROUP BY provider_id"
            )
        }
    used_by = {}
    for g in groups.list_all():
        if g["provider_id"] is not None:
            used_by[g["provider_id"]] = used_by.get(g["provider_id"], 0) + 1
    return admin.render(
        request,
        "providers.html",
        providers=providers.list_all(),
        default_id=groups.global_settings()["default_provider_id"],
        kinds={k: KIND_HELP.get(k, "") for k in providers.KINDS},
        answered=answered,
        used_by=used_by,
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
    row = admin_api.add_provider(fields)
    return admin.redirect("/admin/providers", f"Added {row['name']}. Press Test to make one real call.")


# Before the /providers/{provider_id} routes, or "models" is parsed as an id.
@actions.post("/providers/models", response_class=HTMLResponse)
def list_models(
    request: Request,
    target: str = Form(),
    kind: str = Form(),
    api_key: str = Form(""),
    base_url: str = Form(""),
    provider_id: str = Form(""),
):
    """Ask the provider what this key can use, and hand back a dropdown. The key
    may be the one already stored, which is why an id is accepted instead."""
    if kind not in providers.KINDS:
        raise HTTPException(422, "unknown kind")
    stored = providers.get(int(provider_id)) if provider_id.strip() else None
    if not api_key and stored is None:
        return HTMLResponse('<span class="bad">Paste the key first.</span>')
    probe = {
        "kind": kind,
        "api_key": api_key or stored["api_key"],
        "base_url": base_url or (stored["base_url"] if stored else None),
    }
    try:
        names = providers.models(probe)
    except Exception as e:  # any provider or network failure reads the same here
        return HTMLResponse(f'<span class="bad">Could not list models: {admin.escape(str(e))}</span>')
    if not names:
        return HTMLResponse('<span class="bad">The provider returned no models.</span>')
    return admin.render(request, "model_picker.html", names=names, target=target)


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
    return admin.redirect("/admin/providers", f"Saved {name}.")


@actions.post("/providers/{provider_id}/delete")
def delete(provider_id: int):
    row = providers.get(provider_id)
    admin_api.remove_provider(provider_id)
    return admin.redirect("/admin/providers", f"Deleted {row['name'] if row else 'the provider'}.")


@actions.post("/providers/{provider_id}/default")
def make_default(provider_id: int):
    if providers.get(provider_id) is None:
        raise HTTPException(404)
    groups.set_global(default_provider_id=provider_id)
    audit.log("settings.update", "global", {"default_provider_id": provider_id})
    row = providers.get(provider_id)
    return admin.redirect(
        "/admin/providers", f"{row['name']} now answers in every group without its own choice."
    )


@actions.post("/providers/{provider_id}/test", response_class=HTMLResponse)
def test(provider_id: int):
    try:
        reply = admin_api.run_provider_test(provider_id)
    except HTTPException as e:
        return HTMLResponse(f'<span class="bad">Failed: {admin.escape(str(e.detail))}</span>')
    return HTMLResponse(f'<span class="ok">OK, replied "{admin.escape(reply[:60])}"</span>')
