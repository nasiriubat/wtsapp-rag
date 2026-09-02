import os

import psycopg
from psycopg.rows import dict_row

# Compose reaches Postgres as "db"; CI runs it on localhost and sets DATABASE_URL.
DSN = os.environ.get("DATABASE_URL") or (
    f"postgresql://assistant:{os.environ['POSTGRES_PASSWORD']}@db:5432/assistant"
)


def connect():
    # One connection per unit of work. Endpoints run in FastAPI's threadpool, and
    # a shared psycopg connection is not safe across threads.
    return psycopg.connect(DSN, autocommit=True, row_factory=dict_row)
