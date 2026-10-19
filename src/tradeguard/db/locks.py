from contextlib import contextmanager

from sqlalchemy import text

from tradeguard.db import engine


@contextmanager
def named_lock(name: str):
    with engine().connect() as connection:
        key = f"{connection.engine.url.database}:{name}"[:64]
        if connection.scalar(text("SELECT GET_LOCK(:key, 0)"), {"key": key}) != 1:
            raise ValueError("Another task of this kind is running")
        try:
            yield
        finally:
            connection.execute(text("SELECT RELEASE_LOCK(:key)"), {"key": key})
