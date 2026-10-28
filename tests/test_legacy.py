from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradeguard.db.models import DailyBar, Run
from tradeguard.market import legacy
from tradeguard.market.coverage import source_coverage


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def fetchmany(self, count):
        batch, self.rows = self.rows[:count], self.rows[count:]
        return batch


class Source:
    def __init__(self):
        self.readonly = False

    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def commit(self):
        pass

    def dispose(self):
        pass

    def execution_options(self, **kwargs):
        return self

    def execute(self, query, params=None):
        sql = str(query)
        if sql.startswith("SET SESSION TRANSACTION READ ONLY"):
            self.readonly = True
            return Result([])
        assert self.readonly, "Source must enter read-only mode before querying"
        if "FROM mkt_securities" in sql:
            return Result([{"symbol": "600000.SH", "name": "Synthetic", "industry": "Synthetic"}])
        assert sql.startswith("SELECT ")
        rows = [
            {
                "id": n,
                "symbol": "600000.SH",
                "trade_date": date(2026, 10, 14 + n),
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10 if n == 1 else 0,
                "volume": 1000,
                "turnover": 10000,
            }
            for n in (1, 2)
        ]
        rows = [r for r in rows if r["id"] > params["last_id"]]
        if "maximum" in params:
            rows = rows[: params["maximum"]]
        return Result(rows)


def test_readonly_import_copy_resume_and_invalid_bar_accounting(database, monkeypatch):
    monkeypatch.setenv("TRADEGUARD_SELECTION_SOURCE_URL", "mysql+pymysql://synthetic")
    source = Source()
    monkeypatch.setattr(legacy, "open_readonly", lambda *args, **kwargs: source)
    first = legacy.import_mysql(max_rows=1, batch_size=1)
    assert first["complete"] is False and first["rows_imported"] == 1
    second = legacy.import_mysql(resume_run=first["run_id"], batch_size=1)
    assert second["complete"] is True
    assert second["rows_imported"] == 1 and second["rows_skipped"] == 1
    assert second["last_id"] == 2
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(DailyBar)) == 1
        assert db.get(Run, first["run_id"]).details["last_id"] == 2
    third = legacy.import_mysql(resume_run=first["run_id"])
    assert third["rows_imported"] == 1
    with Session(database) as db:
        coverage = source_coverage(db, "CN", date(2026, 10, 26))
        assert len(coverage) == 1
        assert coverage[0]["rows"] == 1
        assert coverage[0]["symbols"] == 1
        assert coverage[0]["source"] == "legacy_mysql"
