"""Admin JSON API. One admin, HTTP Basic, every write audited. The panel
calls the same add/apply helpers, so validation lives here once."""

import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field, ValidationError

import audit
import bootstrap
import channels
import db
import groups
import providers
from admin import auth

basic = HTTPBasic()


def require_admin(request: Request, creds: HTTPBasicCredentials = Depends(basic)):
    # Same lockout as the panel: this must not be an unthrottled password oracle.
    ok_user = secrets.compare_digest(creds.username.encode(), b"admin")
    if not (ok_user and auth.check_password(creds.password, request.client.host if request.client else "?")):
        raise HTTPException(401, "admin credentials required", headers={"WWW-Authenticate": "Basic"})


router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])


def _validate(model, fields):
    try:
        return model(**fields)
    except ValidationError as e:
        raise HTTPException(422, str(e)) from e


# --- providers -------------------------------------------------------------


class ProviderIn(BaseModel):
    name: str
    kind: str
    api_key: str
    model: str
    base_url: str | None = None
    price_in: float = Field(0, ge=0)
    price_out: float = Field(0, ge=0)
    options: dict = {}
    enabled: bool = True


class ProviderPatch(BaseModel):
    name: str | None = None
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    price_in: float | None = Field(None, ge=0)
    price_out: float | None = Field(None, ge=0)
    options: dict | None = None
    enabled: bool | None = None


def add_provider(fields):
    """Validate, create, audit, and make it the default if there is none."""
    body = _validate(ProviderIn, fields)
    if body.kind not in providers.KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(providers.KINDS)}")
    row = providers.create(**body.model_dump())
    audit.log("provider.create", str(row["id"]), body.model_dump())
    bootstrap.ensure_default(prefer=row["id"])
    return row


def apply_provider(provider_id, fields):
    clean = _validate(ProviderPatch, fields).model_dump(exclude_none=True)
    if not clean:
        raise HTTPException(422, "nothing to update")
    row = providers.update(provider_id, **clean)
    if row is None:
        raise HTTPException(404)
    audit.log("provider.update", str(provider_id), clean)
    # Disabling the default leaves the install unable to answer; adopt another.
    bootstrap.ensure_default()
    return row


def remove_provider(provider_id):
    providers.delete(provider_id)
    audit.log("provider.delete", str(provider_id))
    bootstrap.ensure_default()


def run_provider_test(provider_id):
    provider = providers.get(provider_id)
    if provider is None:
        raise HTTPException(404)
    try:
        reply = providers.check(provider)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"{e.response.status_code}: {e.response.text[:300]}") from e
    except httpx.TransportError as e:
        raise HTTPException(502, f"unreachable: {e}") from e
    audit.log("provider.test", str(provider_id), {"reply": reply})
    return reply


@router.get("/providers")
def list_providers():
    return providers.list_all()


@router.post("/providers", status_code=201)
def create_provider(body: ProviderIn):
    return add_provider(body.model_dump())


@router.patch("/providers/{provider_id}")
def patch_provider(provider_id: int, body: ProviderPatch):
    return apply_provider(provider_id, body.model_dump(exclude_none=True))


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: int):
    remove_provider(provider_id)


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: int):
    return {"ok": True, "reply": run_provider_test(provider_id)}


# --- groups ----------------------------------------------------------------


class GroupIn(BaseModel):
    channel: str
    external_id: str
    name: str | None = None
    settings: groups.Settings = groups.Settings()
    provider_id: int | None = None
    enabled: bool = True


class GroupPatch(BaseModel):
    name: str | None = None
    settings: groups.Settings | None = None
    provider_id: int | None = None
    enabled: bool | None = None


def add_group(fields):
    body = _validate(GroupIn, fields)
    if body.channel not in channels.KINDS:
        raise HTTPException(422, f"channel must be one of {sorted(channels.KINDS)}")
    external_id = body.external_id.strip()
    if not external_id:
        raise HTTPException(422, "id is required")
    if groups.get(external_id):
        raise HTTPException(409, "group already exists")
    row = groups.create(
        **{**body.model_dump(), "external_id": external_id, "settings": body.settings.model_dump()}
    )
    audit.log("group.create", external_id, {"channel": body.channel, "name": body.name})
    return row


def apply_group(group_id, fields):
    """Update, purge newly opted-out members, audit."""
    clean = _validate(GroupPatch, fields).model_dump(exclude_unset=True)
    if not clean:
        raise HTTPException(422, "nothing to update")
    if clean.get("provider_id") is not None and providers.get(clean["provider_id"]) is None:
        raise HTTPException(422, "that provider no longer exists")
    row, purged = groups.apply(group_id, **clean)
    if row is None:
        raise HTTPException(404)
    audit.log("group.update", str(group_id), clean)
    for sender, n in purged:
        audit.log("member.purge", row["external_id"], {"sender": sender, "messages": n})
    return row


@router.get("/groups")
def list_groups():
    return groups.list_all()


@router.post("/groups", status_code=201)
def create_group(body: GroupIn):
    return add_group(body.model_dump())


@router.patch("/groups/{group_id}")
def patch_group(group_id: int, body: GroupPatch):
    return apply_group(group_id, body.model_dump(exclude_unset=True))


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: int):
    groups.delete(group_id)
    audit.log("group.delete", str(group_id))


# --- global settings, questions, audit -------------------------------------


@router.get("/settings")
def get_settings():
    return groups.global_settings()


@router.put("/settings")
def put_settings(body: groups.GlobalSettings):
    clean = groups.set_global(**body.model_dump())
    audit.log("settings.update", "global", clean)
    return clean


@router.get("/questions")
def questions(limit: int = 50, before: int | None = None):
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM query_log WHERE (%(before)s::bigint IS NULL OR id < %(before)s) "
            "ORDER BY id DESC LIMIT %(limit)s",
            {"before": before, "limit": min(limit, 500)},
        ).fetchall()


@router.get("/audit")
def audit_entries(limit: int = 100):
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT %s", (min(limit, 500),)
        ).fetchall()
