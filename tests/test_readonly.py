import pytest
from sqlalchemy import create_engine, text

from tradeguard.db.readonly import install_readonly_guard


def test_source_guard_blocks_writes_and_allows_reads():
    sql_engine = create_engine("sqlite://")
    with sql_engine.begin() as connection:
        connection.execute(text("CREATE TABLE sample (id INTEGER)"))
        connection.execute(text("INSERT INTO sample VALUES (1)"))
    install_readonly_guard(sql_engine)
    with sql_engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM sample")).scalar() == 1
        with pytest.raises(PermissionError):
            connection.execute(text("INSERT INTO sample VALUES (2)"))
        with pytest.raises(PermissionError):
            connection.execute(text("UPDATE sample SET id = 3"))
        with pytest.raises(PermissionError):
            connection.execute(text("DELETE FROM sample"))
