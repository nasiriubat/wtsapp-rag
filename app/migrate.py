import pathlib

import db

DIR = pathlib.Path(__file__).resolve().parent / "migrations"


def run():
    with db.connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        applied = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(DIR.glob("*.sql")):
            if path.name in applied:
                continue
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
            print(f"applied {path.name}")
