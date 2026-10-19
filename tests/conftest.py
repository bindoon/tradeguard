import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tradeguard.db import engine


@pytest.fixture
def database(monkeypatch):
    """Each integration test owns a separate MySQL database; never truncate application tables."""
    url = os.environ.get(
        "TRADEGUARD_TEST_ADMIN_URL",
        "mysql+pymysql://root:tradeguard_dev_root@127.0.0.1:53306/mysql?charset=utf8mb4",
    )
    name = "test_tradeguard_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(
            text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
        )
    test_engine = create_engine(make_url(url).set(database=name))
    monkeypatch.setattr("tradeguard.db.engine", lambda: test_engine)
    monkeypatch.setattr("tradeguard.cli.engine", lambda: test_engine)
    monkeypatch.setattr("tradeguard.market.legacy.engine", lambda: test_engine)
    monkeypatch.setattr("tradeguard.db.locks.engine", lambda: test_engine)
    command.upgrade(Config("alembic.ini"), "head")
    yield test_engine
    test_engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f"DROP DATABASE `{name}`"))
    admin.dispose()
    engine.cache_clear()
