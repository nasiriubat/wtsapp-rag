import os

import pytest

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
