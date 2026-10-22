"""Engines that may read legacy source databases and must not write to them."""

import re

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

_WRITE = re.compile(
    r"^\s*(?:/\*.*?\*/\s*)*(insert|update|delete|replace|alter|drop|create|truncate|"
    r"grant|revoke|rename|call|load|lock|unlock|handler)\b",
    re.IGNORECASE | re.DOTALL,
)


def install_readonly_guard(sql_engine: Engine) -> Engine:
    """Reject mutating statements and, on MySQL, set the session read-only."""

    @event.listens_for(sql_engine, "before_cursor_execute")
    def _guard(conn, cursor, statement, parameters, context, executemany):
        if _WRITE.match(statement or ""):
            raise PermissionError("Refusing to write to a read-only source database")

    if sql_engine.dialect.name == "mysql":

        @event.listens_for(sql_engine, "connect")
        def _session_readonly(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
            finally:
                cursor.close()

    return sql_engine


def open_readonly(url: str, **kwargs) -> Engine:
    connect_args = dict(kwargs.pop("connect_args", {}))
    sql_engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True, **kwargs)
    return install_readonly_guard(sql_engine)
