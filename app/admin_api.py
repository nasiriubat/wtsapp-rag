"""Admin JSON API. One admin, HTTP Basic, every write audited."""

import json
import os
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

import db
import groups
import providers

basic = HTTPBasic()


def require_admin(creds: HTTPBasicCredentials = Depends(basic)):
    ok_user = secrets.compare_digest(creds.username.encode(), b"admin")
    ok_pass = secrets.compare_digest(creds.password.encode(), os.environ["ADMIN_PASSWORD"].encode())
    if not (ok_user and ok_pass):
        raise HTTPException(401, "admin credentials required", headers={"WWW-Authenticate": "Basic"})


router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])


def audit(action, target, detail=None):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (actor, action, target, detail) VALUES (%s, %s, %s, %s)",
            ("admin", action, target, json.dumps(detail, default=str) if detail is not None else None),
        )


def _redact(detail):
    return {k: ("***" if k == "api_key" else v) for k, v in detail.items()}


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


@router.get("/providers")
def list_providers():
    return providers.list_all()


@router.post("/providers", status_code=201)
def create_provider(body: ProviderIn):
    if body.kind not in providers.KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(providers.KINDS)}")
    row = providers.create(**body.model_dump())
    audit("provider.create", str(row["id"]), _redact(body.model_dump()))
    return row


@router.patch("/providers/{provider_id}")
def patch_provider(provider_id: int, body: ProviderPatch):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(422, "nothing to update")
    row = providers.update(provider_id, **fields)
    if row is None:
        raise HTTPException(404)
    audit("provider.update", str(provider_id), _redact(fields))
    return row


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: int):
    providers.delete(provider_id)
    audit("provider.delete", str(provider_id))


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: int):
    provider = providers.get(provider_id)
    if provider is None:
        raise HTTPException(404)
    try:
        reply = providers.check(provider)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"{e.response.status_code}: {e.response.text[:300]}") from e
    except httpx.TransportError as e:
        raise HTTPException(502, f"unreachable: {e}") from e
    audit("provider.test", str(provider_id), {"reply": reply})
    return {"ok": True, "reply": reply}


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


@router.get("/groups")
def list_groups():
    return groups.list_all()


@router.post("/groups", status_code=201)
def create_group(body: GroupIn):
    if groups.get(body.external_id):
        raise HTTPException(409, "group already exists")
    row = groups.create(**{**body.model_dump(), "settings": body.settings.model_dump()})
    audit("group.create", body.external_id, body.model_dump())
    return row


@router.patch("/groups/{group_id}")
def patch_group(group_id: int, body: GroupPatch):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "nothing to update")
    row = groups.update(group_id, **fields)
    if row is None:
        raise HTTPException(404)
    audit("group.update", str(group_id), fields)
    return row


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: int):
    groups.delete(group_id)
    audit("group.delete", str(group_id))


# --- global settings, questions, audit -------------------------------------


@router.get("/settings")
def get_settings():
    return groups.global_settings()


@router.put("/settings")
def put_settings(body: groups.GlobalSettings):
    clean = groups.set_global(**body.model_dump())
    audit("settings.update", "global", clean)
    return clean


@router.get("/questions")
def questions(limit: int = 50, before: int | None = None):
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM query_log WHERE (%s::bigint IS NULL OR id < %s) ORDER BY id DESC LIMIT %s",
            (before, before, min(limit, 500)),
        ).fetchall()


@router.get("/audit")
def audit_entries(limit: int = 100):
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT %s", (min(limit, 500),)
        ).fetchall()
