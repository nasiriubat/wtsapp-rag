import logging
import pathlib

import db

DIR = pathlib.Path(__file__).resolve().parent / "migrations"
log = logging.getLogger(__name__)


def run():
    with db.connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        applied = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        # v0.1 created the schema through initdb, before this runner existed.
        # Adopt such a database by recording 001 as applied instead of re-running it.
        if not applied and conn.execute("SELECT to_regclass('messages') AS t").fetchone()["t"]:
            conn.execute("INSERT INTO schema_migrations (version) VALUES ('001_init.sql')")
            applied.add("001_init.sql")
        for path in sorted(DIR.glob("*.sql")):
            if path.name in applied:
                continue
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
            log.info("applied %s", path.name)
