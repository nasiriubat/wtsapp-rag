"""Admin login: one password, a signed session cookie, CSRF on every POST."""

import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import quote

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, TimestampSigner

COOKIE = "admin_session"
MAX_AGE = 7 * 86400
PER_CLIENT = 5  # wrong guesses before one client waits
GLOBAL = 20  # wrong guesses a minute from everyone before everyone waits
LOCK = 60
MAX_TRACKED = 10_000

# Two throttles. Per client, so one guesser cannot lock the admin out. And a
# global one, because "the client" is whatever X-Forwarded-For says once a
# proxy is in front: rotating that header must not buy a fresh allowance.
_failures = {}  # (scope, client) -> {"count", "until"}
_global = {"count": 0, "since": 0.0, "until": 0.0}


def _signer():
    # The password is part of the salt, so changing it invalidates every
    # session that was signed under the old one. Rotating a leaked password
    # then logs the thief out as well as you.
    fingerprint = hashlib.sha256(os.environ["ADMIN_PASSWORD"].encode()).hexdigest()[:16]
    return TimestampSigner(os.environ["SECRET_KEY"], salt=f"admin-session:{fingerprint}")


def _sweep(now):
    if len(_failures) > MAX_TRACKED:
        _failures.clear()  # the global throttle still holds
        return
    for key in [k for k, f in _failures.items() if f["count"] == 0 and now >= f["until"]]:
        _failures.pop(key, None)


def check_password(password, client, scope="panel"):
    now = time.time()
    _sweep(now)
    if now < _global["until"]:
        raise HTTPException(429, "too many attempts; wait a minute")
    f = _failures.setdefault((scope, client), {"count": 0, "until": 0.0})
    if now < f["until"]:
        raise HTTPException(429, "too many attempts; wait a minute")
    if secrets.compare_digest(password.encode(), os.environ["ADMIN_PASSWORD"].encode()):
        _failures.pop((scope, client), None)
        return True
    f["count"] += 1
    if f["count"] >= PER_CLIENT:
        f.update(count=0, until=now + LOCK)
    if now - _global["since"] > LOCK:
        _global.update(count=0, since=now)
    _global["count"] += 1
    if _global["count"] >= GLOBAL:
        _global.update(count=0, since=now, until=now + LOCK)
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
        # Back to the page that was asked for, once signed in. Only a path on
        # this site: a full URL here would be an open redirect.
        wanted = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise HTTPException(303, headers={"Location": f"/admin/login?next={quote(wanted, safe='/?=&')}"})


def safe_next(value):
    return value if value.startswith("/") and not value.startswith("//") else "/admin"


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
