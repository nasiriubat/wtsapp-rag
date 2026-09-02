import os

import psycopg
from psycopg.rows import dict_row


def connect():
    # Read at call time so importing any module never needs a database.
    # One connection per unit of work: endpoints run in FastAPI's threadpool, and
    # a shared psycopg connection is not safe across threads.
    return psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row)
