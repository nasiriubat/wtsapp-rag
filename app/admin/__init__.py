"""Server-rendered admin panel. Pages live in one module each under admin/."""

import html
import os
import pathlib

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer

import gateway_state
from admin import auth
from version import VERSION

FLASH = "flash"

templates = Jinja2Templates(directory=str(pathlib.Path(__file__).resolve().parent.parent / "templates"))
escape = html.escape

public = APIRouter(prefix="/admin")
router = APIRouter(prefix="/admin", dependencies=[Depends(auth.require_session)])
forms = APIRouter(prefix="/admin", dependencies=[Depends(auth.require_session), Depends(auth.require_csrf)])
setup_pages = APIRouter(prefix="/setup", dependencies=[Depends(auth.require_session)])
setup_forms = APIRouter(
    prefix="/setup", dependencies=[Depends(auth.require_session), Depends(auth.require_csrf)]
)


def _flash_signer():
    return URLSafeSerializer(os.environ["SECRET_KEY"], salt="flash")


def take_flash(request):
    """The one-line result of the last action, or None. Signed, so a crafted
    link cannot put words in the panel's mouth, and read once."""
    raw = request.cookies.get(FLASH)
    if not raw:
        return None
    try:
        return _flash_signer().loads(raw)
    except BadSignature:
        return None


def render(request, name, status_code=200, **ctx):
    flash = take_flash(request)
    # The wizard's own pages explain a missing link themselves.
    trouble = [] if request.url.path.startswith("/setup") else gateway_state.trouble()
    response = templates.TemplateResponse(
        request,
        name,
        {"csrf": auth.csrf_token(request), "flash": flash, "trouble": trouble, "version": VERSION, **ctx},
        status_code=status_code,
    )
    if flash is not None:
        response.delete_cookie(FLASH)
    return response


def redirect(path, message, kind="ok"):
    """Post-redirect-get with the result shown once on the next page."""
    response = RedirectResponse(path, status_code=303)
    response.set_cookie(
        FLASH,
        _flash_signer().dumps({"kind": kind, "text": message}),
        max_age=60,
        httponly=True,
        samesite="lax",
    )
    return response


def error_response(request, status, detail):
    """A form that failed, as a page a person can read, with the way back."""
    if request.headers.get("hx-request"):
        return HTMLResponse(f'<div class="notice bad" role="alert">{html.escape(str(detail))}</div>', status)
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "csrf": auth.csrf_token(request),
            "flash": None,
            "trouble": [],
            "version": VERSION,
            "status": status,
            "detail": detail,
            "back": request.headers.get("referer") or "/admin",
        },
        status_code=status,
    )


@public.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/admin"):
    return templates.TemplateResponse(
        request, "login.html", {"error": None, "next": auth.safe_next(next), "version": VERSION}
    )


@public.post("/login")
def login(request: Request, password: str = Form(), next: str = Form("/admin")):
    if not auth.check_password(password, request.client.host if request.client else "?"):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Wrong password.", "next": auth.safe_next(next), "version": VERSION},
            status_code=401,
        )
    res = RedirectResponse(auth.safe_next(next), status_code=303)
    res.set_cookie(
        auth.COOKIE,
        auth.new_session(),
        max_age=auth.MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return res


@forms.post("/logout")
def logout():
    res = RedirectResponse("/admin/login", status_code=303)
    res.delete_cookie(auth.COOKIE)
    return res


# Pages import this module for the routers above, so they load last. health and
# setup register their index pages on the prefixed routers directly.
from admin import (  # noqa: E402
    health,  # noqa: F401
    pages_audit,
    pages_channels,
    pages_cost,
    pages_data,
    pages_documents,
    pages_groups,
    pages_providers,
    pages_questions,
    setup,
)

setup_pages.include_router(setup.pages)
setup_forms.include_router(setup.actions)
for module in (
    pages_providers,
    pages_groups,
    pages_questions,
    pages_cost,
    pages_data,
    pages_documents,
    pages_channels,
    pages_audit,
):
    router.include_router(module.pages)
    forms.include_router(module.actions)
