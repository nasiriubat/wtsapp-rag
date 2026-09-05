import os

import pytest
from conftest import needs_db

pytestmark = needs_db


@pytest.fixture()
def browser(client):
    client.cookies.clear()
    yield client
    client.cookies.clear()


def login(browser):
    res = browser.post(
        "/admin/login", data={"password": os.environ["ADMIN_PASSWORD"]}, follow_redirects=False
    )
    assert res.status_code == 303 and res.headers["location"] == "/admin"
    return res


def test_pages_redirect_to_login_without_a_session(browser):
    res = browser.get("/admin", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/admin/login"


def test_wrong_password_is_rejected(browser):
    res = browser.post("/admin/login", data={"password": "nope"})
    assert res.status_code == 401 and "Wrong password" in res.text
    assert "admin_session" not in browser.cookies


def test_login_sets_a_signed_cookie_and_health_renders(browser):
    login(browser)
    assert "admin_session" in browser.cookies
    res = browser.get("/admin")
    assert res.status_code == 200
    assert "Health" in res.text and "Questions, last 24 h" in res.text
    assert res.headers["content-security-policy"].startswith("default-src 'self'")


def test_tampered_cookie_is_a_logout(browser):
    login(browser)
    browser.cookies.set("admin_session", "forged.value")
    assert browser.get("/admin", follow_redirects=False).status_code == 303


def test_posts_need_the_csrf_token(browser):
    login(browser)
    assert browser.post("/admin/logout", follow_redirects=False).status_code == 403
    page = browser.get("/admin").text
    token = page.split('name="csrf" value="')[1].split('"')[0]
    res = browser.post("/admin/logout", data={"csrf": token}, follow_redirects=False)
    assert res.status_code == 303
    assert browser.get("/admin", follow_redirects=False).status_code == 303


def test_static_assets_are_served(client):
    assert client.get("/static/htmx.min.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def csrf_of(browser):
    return browser.get("/admin").text.split('name="csrf" value="')[1].split('"')[0]


def test_a_form_error_comes_back_as_a_page_with_the_way_back(browser):
    login(browser)
    csrf = csrf_of(browser)
    res = browser.post(
        "/admin/cost/cap",
        data={"csrf": csrf, "monthly_cap_eur": "ten euros"},
        headers={"accept": "text/html", "referer": "/admin/cost"},
    )
    assert res.status_code == 422
    assert "monthly cap" in res.text and 'href="/admin/cost"' in res.text and "Go back" in res.text
    # An htmx call gets a fragment it can drop into the page instead.
    res = browser.post(
        "/admin/cost/cap",
        data={"csrf": csrf, "monthly_cap_eur": "ten euros"},
        headers={"accept": "text/html", "hx-request": "true"},
    )
    assert res.status_code == 422 and res.text.startswith('<div class="notice bad"')


def test_a_crafted_flash_cookie_is_ignored(browser):
    login(browser)
    browser.cookies.set("flash", "eyJraW5kIjogIm9rIiwgInRleHQiOiAiWW91ciBrZXkgZXhwaXJlZCJ9.forged")
    assert "Your key expired" not in browser.get("/admin").text
