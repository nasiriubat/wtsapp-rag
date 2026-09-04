"""What the gateway process is allowed to call, behind a shared token."""

import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

import channels
import gateway_state
import groups


def require_token(authorization: str = Header(default="")):
    expected = f"Bearer {os.environ['GATEWAY_TOKEN']}"
    if not secrets.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(401, "gateway token required")


router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/gateway/config")
def config():
    return {
        "channels": [
            {"kind": c["kind"], "config": c["config"]}
            for c in channels.list_all(with_config=True)
            if c["enabled"]
        ],
        "groups": [
            {"external_id": g["external_id"], "channel": g["channel"], "triggers": g["settings"]["triggers"]}
            for g in groups.list_all()
            if g["enabled"]
        ],
        "relink": gateway_state.take_relink(),
    }


class SeenGroup(BaseModel):
    id: str
    subject: str | None = None
    members: list[str] = []  # sender ids, where the channel can list them


class State(BaseModel):
    channel: str = "whatsapp"
    connected: bool
    jid: str | None = None
    qr: str | None = None
    groups: list[SeenGroup] = []


@router.post("/gateway/state")
def state(body: State):
    if body.channel not in channels.KINDS:
        raise HTTPException(422, "unknown channel")
    gateway_state.update(**body.model_dump())
    return {"ok": True}
