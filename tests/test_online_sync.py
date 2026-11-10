import os
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from tradeguard import online_sync
from tradeguard.db.models import (
    Account,
    DailyBar,
    PortfolioSnapshot,
    Run,
    ScanResult,
    ScanSummary,
    Security,
)

DAY = date(2026, 11, 10)


@pytest.fixture
def online(database, monkeypatch):
    """A second throwaway database standing in for the online `tradeguard` DB."""
    admin_url = os.environ.get(
        "TRADEGUARD_TEST_ADMIN_URL",
        "mysql+pymysql://root:tradeguard_dev_root@127.0.0.1:53306/mysql?charset=utf8mb4",
    )
    name = "test_tradeguard_online_" + uuid4().hex[:16]
    admin = create_engine(admin_url)
    with admin.begin() as connection:
        connection.execute(
            text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
        )
    url = make_url(admin_url).set(database=name)
    target = create_engine(url)
    monkeypatch.setattr("tradeguard.db.engine", lambda: target)
    command.upgrade(Config("alembic.ini"), "head")
    monkeypatch.setattr("tradeguard.db.engine", lambda: database)
    monkeypatch.setattr(online_sync, "ONLINE_DATABASE", name)
    yield target, url.render_as_string(hide_password=False)
    target.dispose()
    with admin.begin() as connection:
        connection.execute(text(f"DROP DATABASE `{name}`"))
    admin.dispose()


def _seed_local(engine):
    with Session(engine) as db, db.begin():
        for symbol, name in [("600000.SH", "测试银行"), ("000001.SZ", "测试平安")]:
            db.add(Security(symbol=symbol, name=name, market="CN", currency="CNY", industry="银行"))
        db.flush()
        run = Run(
            kind="scan",
            status="partial",
            market="CN",
            market_date=DAY,
            details={"source": "baostock", "adjustment": "forward"},
        )
        db.add(run)
        db.flush()
        for symbol, hits in [("600000.SH", ["a", "b"]), ("000001.SZ", ["a"])]:
            db.add(
                ScanResult(
                    run_id=run.id,
                    symbol=symbol,
                    trade_date=DAY,
                    hits=hits,
                    close=Decimal("10.5"),
                    resonance_count=len(hits),
                )
            )
            db.add(
                DailyBar(
                    symbol=symbol,
                    trade_date=DAY,
                    source="baostock",
                    adjustment="forward",
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("9"),
                    close=Decimal("10.5"),
                    volume=Decimal("1000"),
                )
            )
        db.add(
            ScanSummary(
                run_id=run.id,
                market="CN",
                trade_date=DAY,
                source="baostock",
                adjustment="forward",
                status="partial",
                hit_count=2,
                resonance_count=1,
            )
        )
        db.add(Account(id="cms-test", broker="cms", label="测试"))
        db.flush()
        for index, external in enumerate(["old", "new"]):
            db.add(
                PortfolioSnapshot(
                    account_id="cms-test",
                    external_id=external,
                    as_of=datetime(2026, 11, 1 + index, tzinfo=timezone.utc),
                    payload={"positions": [], "n": index},
                )
            )
        return run.id


def _seed_stale(target):
    with Session(target) as db, db.begin():
        db.add(Security(symbol="600001.SH", name="旧", market="CN", currency="CNY"))
        db.flush()
        stale = Run(kind="scan", status="partial", market="CN", market_date=DAY, details={})
        db.add(stale)
        db.flush()
        db.add(
            ScanResult(
                run_id=stale.id, symbol="600001.SH", trade_date=DAY, hits=["x"], close=Decimal(1)
            )
        )
        db.add(
            ScanSummary(
                run_id=stale.id,
                market="CN",
                trade_date=DAY,
                source="baostock",
                adjustment="forward",
                status="partial",
            )
        )
        return stale.id


def _count(target, model, *where):
    with Session(target) as db:
        return db.scalar(select(func.count()).select_from(model).where(*where))


def test_sync_mirrors_one_day_and_latest_snapshots(database, online):
    target, url = online
    run_id = _seed_local(database)
    stale_id = _seed_stale(target)

    for _ in range(2):  # idempotent
        result = online_sync.sync_online(DAY, url=url)
        assert result["status"] == "success"
        assert result["dates"][0]["scan_result"] == 2
        assert result["portfolio"] == {"account": 1, "portfolio_snapshot": 1}

    assert _count(target, ScanResult, ScanResult.run_id == run_id) == 2
    assert _count(target, ScanResult, ScanResult.run_id == stale_id) == 0
    assert _count(target, Run, Run.id == stale_id) == 0
    assert _count(target, ScanSummary, ScanSummary.trade_date == DAY) == 1
    assert _count(target, DailyBar) == 0  # bars are opt-in
    with Session(target) as db:
        snaps = db.scalars(select(PortfolioSnapshot)).all()
    assert [s.external_id for s in snaps] == ["new"]

    online_sync.sync_online(DAY, url=url, bars=True, portfolio=False)
    assert _count(target, DailyBar, DailyBar.trade_date == DAY) == 2


def test_target_guard_refuses_other_databases(database, online, monkeypatch):
    _, url = online
    base = make_url(url)
    online_sync.check_target(url)
    for name in ["stock_market", "stock_portfolio", "tradeguard_other"]:
        with pytest.raises(ValueError):
            online_sync.check_target(base.set(database=name).render_as_string(False))
    # The right name on the local runtime server/database is still refused.
    monkeypatch.setenv("TRADEGUARD_DATABASE_URL", url)
    with pytest.raises(ValueError, match="local runtime"):
        online_sync.check_target(url)


def test_pipeline_hook_never_raises(database, monkeypatch):
    monkeypatch.setenv("TRADEGUARD_ONLINE_DATABASE_URL", "mysql+pymysql://u:secret@127.0.0.1:1/x")
    result = online_sync.sync_after_pipeline([DAY])
    assert result is not None and result["status"] == "failed"
    assert "secret" not in result["error"]
    monkeypatch.setenv("TRADEGUARD_ONLINE_DATABASE_URL", "")
    assert online_sync.sync_after_pipeline([DAY]) is None
