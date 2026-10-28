from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from tradeguard.console import create_app
from tradeguard.db import session
from tradeguard.db.models import DailyBar, Run, ScanResult, ScanSummary, Security
from tradeguard.market.coverage import source_coverage
from tradeguard.market.schemas import BarInput
from tradeguard.market.service import save_bars


def bar(symbol, day, source="fixture", adjustment="forward"):
    return BarInput(
        symbol=symbol,
        trade_date=day,
        source=source,
        adjustment=adjustment,
        open="10",
        high="11",
        low="9",
        close="10",
        volume="100",
    )


def assert_matches_bars(target):
    with session() as db:
        for market in ("CN", "US", "HK"):
            actual = source_coverage(db, market, target)
            expected = db.execute(
                select(
                    DailyBar.source,
                    DailyBar.adjustment,
                    func.count(),
                    func.count(func.distinct(DailyBar.symbol)),
                    func.min(DailyBar.trade_date),
                    func.max(DailyBar.trade_date),
                )
                .join(Security, Security.symbol == DailyBar.symbol)
                .where(Security.market == market, DailyBar.trade_date <= target)
                .group_by(DailyBar.source, DailyBar.adjustment)
                .order_by(DailyBar.source, DailyBar.adjustment)
            ).all()
            assert actual == [
                dict(source=s, adjustment=a, rows=n, symbols=sy, min_date=str(mi), max_date=str(ma))
                for s, a, n, sy, mi, ma in expected
            ]


def test_coverage_is_exact_for_retries_backfills_markets_sources_and_future_dates(database):
    day, old, future = date(2025, 6, 20), date(2024, 1, 1), date(2099, 1, 1)
    rows = [
        bar("600000.SH", day),
        bar("600519.SH", day),
        bar("AAPL.US", day),
        bar("00700.HK", day),
        bar("600000.SH", day, "other"),
        bar("600000.SH", day, adjustment="none"),
        bar("600000.SH", future),
        bar("000001.SZ", future),
    ]
    save_bars(rows)
    save_bars(rows)  # An upsert updates prices; it must not inflate saved counts.
    save_bars([bar("600000.SH", old), bar("600519.SH", old)])
    for target in (date(2023, 1, 1), old, day, future):
        assert_matches_bars(target)


def test_concurrent_overlapping_imports_do_not_double_count(database):
    rows = [bar("600000.SH", date(2025, 6, 20)), bar("600000.SH", date(2025, 6, 19))]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save_bars, rows) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)
    assert_matches_bars(date(2025, 6, 20))
    with session() as db:
        assert source_coverage(db, "CN", date(2025, 6, 20))[0]["rows"] == 2


def test_failed_import_rolls_back_bars_and_both_summaries(database, monkeypatch):
    from tradeguard.market import service

    original = service.record_coverage

    def fail(db, added):
        original(db, added)
        raise ValueError("synthetic transaction failure")

    monkeypatch.setattr(service, "record_coverage", fail)
    with pytest.raises(ValueError, match="synthetic transaction failure"):
        save_bars([bar("600000.SH", date(2025, 6, 20))])
    assert_matches_bars(date(2025, 6, 20))
    with session() as db:
        assert source_coverage(db, "CN", date(2025, 6, 20)) == []


def test_migration_backfills_existing_bars_once(database):
    save_bars(
        [
            bar("600000.SH", date(2025, 6, 20)),
            bar("600000.SH", date(2024, 1, 1)),
            bar("AAPL.US", date(2025, 6, 20)),
            bar("600519.SH", date(2099, 1, 1)),
        ]
    )
    config = Config("alembic.ini")
    command.downgrade(config, "e82b9a41d063")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert_matches_bars(date(2025, 6, 20))
    assert_matches_bars(date(2099, 1, 1))


def test_home_reads_saved_metadata_and_scan_without_any_daily_bar_query(database):
    day = date(2025, 6, 20)
    save_bars([bar("600000.SH", day)])
    with session() as db, db.begin():
        run = Run(
            kind="scan",
            market="CN",
            market_date=day,
            status="success",
            details={"source": "fixture", "adjustment": "forward"},
        )
        db.add(run)
        db.flush()
        run_id = run.id
        db.add(
            ScanSummary(
                run_id=run.id,
                market="CN",
                trade_date=day,
                source="fixture",
                adjustment="forward",
                status="success",
                universe_count=1,
                scanned_count=1,
                hit_count=1,
                resonance_count=0,
            )
        )
        db.add(
            ScanResult(
                run_id=run.id,
                symbol="600000.SH",
                trade_date=day,
                hits=["ma_golden_cross"],
                close="10",
                resonance_count=1,
            )
        )
    queries = []

    def capture(conn, cursor, statement, params, context, many):
        queries.append(statement.lower())

    event.listen(database, "before_cursor_execute", capture)
    try:
        # A new app and forced refresh both exercise the uncached request path.
        client = TestClient(create_app())
        for suffix in ("", "&refresh=true"):
            context = client.get("/api/context?market=CN" + suffix)
            assert context.status_code == 200
            assert context.json()["sources"][0]["rows"] == 1
        response = client.get("/api/workspace?market=CN&source=fixture&adjustment=forward")
        assert response.status_code == 200
        report = response.json()["report"]
        assert report["run_id"] == run_id
        assert report["counts"]["hits"] == 1
        assert report["top_resonance"][0]["symbol"] == "600000.SH"
        assert not any("daily_bar" in query for query in queries)
        assert any("bar_date_coverage" in query for query in queries)
        assert any("scan_summary" in query for query in queries)
    finally:
        event.remove(database, "before_cursor_execute", capture)
