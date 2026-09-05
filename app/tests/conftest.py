import os

import pytest

# The suite mutates global settings and runs retention; it must never meet the
# database the panel is using. The name has to say so.
_db_name = os.environ.get("DATABASE_URL", "").rsplit("/", 1)[-1].split("?")[0]
if _db_name and not _db_name.endswith("_test"):
    pytest.exit(f"DATABASE_URL points at {_db_name!r}; tests only run against a database named *_test", 3)

GW = {"authorization": f"Bearer {os.environ.get('GATEWAY_TOKEN', '')}"}
AUTH = ("admin", os.environ.get("ADMIN_PASSWORD", ""))
needs_db = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs Postgres (DATABASE_URL)")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    import migrate
    from main import app

    migrate.run()
    # No lifespan: that would load the models and start the loops.
    return TestClient(app)


@pytest.fixture()
def browser(client):
    """The test client logged into the panel, with the CSRF token on `.csrf`."""
    client.cookies.clear()
    client.post("/admin/login", data={"password": os.environ["ADMIN_PASSWORD"]}, follow_redirects=False)
    client.csrf = client.get("/admin").text.split('name="csrf" value="')[1].split('"')[0]
    yield client
    client.cookies.clear()


def post(browser, path, **data):
    return browser.post(path, data={"csrf": browser.csrf, **data}, follow_redirects=False)


@pytest.fixture()
def stub_embeddings(monkeypatch):
    """The real model lives in the image, not in a unit test."""
    import embed

    monkeypatch.setattr(embed, "passages", lambda texts: [[0.1] * 384 for _ in texts])
    monkeypatch.setattr(embed, "query", lambda text: [0.1] * 384)


@pytest.fixture(autouse=True)
def _fresh_throttle():
    """Tests reuse a few sender ids; none of them is trying to flood the bot."""
    try:
        import asking

        asking._asked.clear()
    except ImportError:
        pass
