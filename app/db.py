import os

import psycopg

DSN = f"postgresql://assistant:{os.environ['POSTGRES_PASSWORD']}@db:5432/assistant"


def connect():
    # One connection per unit of work. Endpoints run in FastAPI's threadpool, and
    # a shared psycopg connection is not safe across threads.
    return psycopg.connect(DSN, autocommit=True)
