"""Server-rendered admin panel. Pages live in one module each under admin/."""

import html
import pathlib
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from admin import auth

templates = Jinja2Templates(directory=str(pathlib.Path(__file__).resolve().parent.parent / "templates"))
escape = html.escape

public = APIRouter(prefix="/admin")
router = APIRouter(prefix="/admin", dependencies=[Depends(auth.require_session)])
forms = APIRouter(prefix="/admin", dependencies=[Depends(auth.require_session), Depends(auth.require_csrf)])
setup_pages = APIRouter(prefix="/setup", dependencies=[Depends(auth.require_session)])
setup_forms = APIRouter(
    prefix="/setup", dependencies=[Depends(auth.require_session), Depends(auth.require_csrf)]
)


def render(request, name, **ctx):
    return templates.TemplateResponse(request, name, {"csrf": auth.csrf_token(request), **ctx})


def redirect(path, message):
    """Post-redirect-get with a one-line flash carried in the query string."""
    return RedirectResponse(f"{path}?{urlencode({'message': message})}", status_code=303)


@public.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@public.post("/login")
def login(request: Request, password: str = Form()):
    if not auth.check_password(password, request.client.host if request.client else "?"):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Wrong password."}, status_code=401
        )
    res = RedirectResponse("/admin", status_code=303)
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
    pages_channels,
    pages_cost,
    pages_data,
    pages_groups,
    pages_providers,
    pages_questions,
    setup,
)

setup_pages.include_router(setup.pages)
setup_forms.include_router(setup.actions)
for module in (pages_providers, pages_groups, pages_questions, pages_cost, pages_data, pages_channels):
    router.include_router(module.pages)
    forms.include_router(module.actions)
