from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tradeguard.config import settings


@lru_cache
def engine():
    return create_engine(
        settings().database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=10,
        max_overflow=10,
    )


def session() -> Session:
    return Session(engine(), expire_on_commit=False)
