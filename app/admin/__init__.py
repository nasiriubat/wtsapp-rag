"""Server-rendered admin panel. Pages live in one module each under admin/."""

import html
import pathlib

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from admin import auth

templates = Jinja2Templates(directory=str(pathlib.Path(__file__).resolve().parent.parent / "templates"))
escape = html.escape

public = APIRouter(prefix="/admin")
router = APIRouter(prefix="/admin", dependencies=[Depends(auth.require_session)])
forms = APIRouter(prefix="/admin", dependencies=[Depends(auth.require_session), Depends(auth.require_csrf)])


def render(request, name, **ctx):
    return templates.TemplateResponse(request, name, {"csrf": auth.csrf_token(request), **ctx})


@public.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@public.post("/login")
def login(request: Request, password: str = Form()):
    if not auth.check_password(password):
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


from admin import (  # noqa: E402  (pages import this module)
    health,
    pages_cost,
    pages_data,
    pages_groups,
    pages_providers,
    pages_questions,
)

# "/admin" itself; a sub-router cannot own an empty path.
router.add_api_route("", health.page, methods=["GET"])
for module in (pages_providers, pages_groups, pages_questions, pages_cost, pages_data):
    router.include_router(module.pages)
    forms.include_router(module.actions)
