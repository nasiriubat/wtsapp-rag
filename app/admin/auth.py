"""Admin login: one password, a signed session cookie, CSRF on every POST."""

import hmac
import os
import secrets
import time

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, TimestampSigner

COOKIE = "admin_session"
MAX_AGE = 7 * 86400
_failures = {}  # client address -> {"count", "until"}; one client cannot lock out another


def _signer():
    return TimestampSigner(os.environ["SECRET_KEY"], salt="admin-session")


def check_password(password, client):
    now = time.time()
    f = _failures.setdefault(client, {"count": 0, "until": 0.0})
    if now < f["until"]:
        raise HTTPException(429, "too many attempts; wait a minute")
    if secrets.compare_digest(password.encode(), os.environ["ADMIN_PASSWORD"].encode()):
        _failures.pop(client, None)
        return True
    f["count"] += 1
    if f["count"] >= 5:
        f.update(count=0, until=now + 60)
    return False


def new_session():
    return _signer().sign(secrets.token_urlsafe(16)).decode()


def session_id(request):
    cookie = request.cookies.get(COOKIE, "")
    try:
        return _signer().unsign(cookie, max_age=MAX_AGE).decode()
    except BadSignature:
        return None


def csrf_token(request):
    sid = session_id(request) or ""
    return hmac.new(os.environ["SECRET_KEY"].encode(), sid.encode(), "sha256").hexdigest()


def require_session(request: Request):
    if session_id(request) is None:
        raise HTTPException(303, headers={"Location": "/admin/login"})


async def require_csrf(request: Request):
    # Forms carry it as a field, htmx calls as a header. The cookie is SameSite=Lax
    # as well; this is the second line.
    sent = request.headers.get("x-csrf-token")
    if sent is None and request.headers.get("content-type", "").startswith(
        ("application/x-www-form-urlencoded", "multipart/form-data")
    ):
        form = await request.form()
        sent = form.get("csrf")
    # Bytes, not str: compare_digest raises on a non-ASCII header.
    if not sent or not hmac.compare_digest(str(sent).encode(), csrf_token(request).encode()):
        raise HTTPException(403, "bad csrf token")
