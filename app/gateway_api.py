"""What the gateway process is allowed to call, behind a shared token."""

import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

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
        "groups": [
            {"external_id": g["external_id"], "channel": g["channel"], "triggers": g["settings"]["triggers"]}
            for g in groups.list_all()
            if g["enabled"]
        ]
    }


class State(BaseModel):
    connected: bool
    jid: str | None = None
    qr: str | None = None
    groups: list[dict] = []  # [{id, subject}] as the channel sees them


@router.post("/gateway/state")
def state(body: State):
    """The gateway reports connection state, the current QR and the groups it
    can see. The setup wizard and the health page read it."""
    gateway_state.update(**body.model_dump())
    return {"ok": True}
