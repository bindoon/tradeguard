from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event

from tradeguard.console import create_app
from tradeguard.db import session
from tradeguard.db.models import Run, ScanResult, Security, now
from tradeguard.market.schemas import BarInput
from tradeguard.market.service import save_bars


def test_history_uses_bounded_queries_and_preserves_historical_industries(database):
    day = date(2025, 6, 20)
    with session() as db, db.begin():
        db.add_all(
            Security(
                symbol=symbol, name="Synthetic", market="CN", currency="CNY", industry="Current"
            )
            for symbol in ["600000.SH", "600001.SH", "600002.SH"]
        )
        db.flush()
        runs = [
            Run(
                kind="scan",
                market="CN",
                market_date=day - timedelta(days=index),
                status="success",
                started_at=now() - timedelta(days=index),
                details={"source": "fixture", "adjustment": "forward", "universe": 4},
            )
            for index in range(12)
        ]
        db.add_all(runs)
        db.flush()
        for run in runs:
            db.add_all(
                ScanResult(
                    run_id=run.id,
                    symbol=symbol,
                    trade_date=run.market_date,
                    hits=hits,
                    close="10",
                    # Older rows may predate the stored resonance counter.
                    resonance_count=0,
                    metadata_snapshot=metadata,
                )
                for symbol, hits, metadata in [
                    ("600000.SH", ["ma_golden_cross", "box_breakout"], {"industry": "Historical"}),
                    ("600001.SH", ["rsi_rebound", "box_breakout"], {"industry": "Historical"}),
                    ("600002.SH", ["box_breakout"], None),
                ]
            )
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(database, "before_cursor_execute", record)
    try:
        response = TestClient(create_app()).get(
            "/api/scan/summaries?market=CN&source=fixture&adjustment=forward"
        )
    finally:
        event.remove(database, "before_cursor_execute", record)
    assert response.status_code == 200
    assert len(statements) == 3, (
        "History uses an ID sort, an unsorted row fetch and one aggregation"
    )
    sorted_queries = [statement for statement in statements if "ORDER BY" in statement]
    assert all("job_run.details" not in statement.split("FROM")[0] for statement in sorted_queries)
    rows = response.json()
    assert len(rows) == 12
    assert rows[0]["scanDate"] == str(day)
    for row in rows:
        assert row["hitStockCount"] == 3
        assert row["candidateCount"] == 2
        assert row["hitIndustryCount"] == 2
        assert row["resonanceIndustryCount"] == 1
        assert row["topSectors"] == [
            {"sector": "Historical", "rs": None, "count": 2},
            {"sector": "Current", "rs": None, "count": 1},
        ]
    client = TestClient(create_app())
    detail = client.get(f"/api/scan/{rows[0]['id']}/summary?market=CN&source=fixture").json()
    assert detail["topSectors"] == rows[0]["topSectors"]
    assert detail["resonanceIndustryCount"] == 1
    assert client.get("/api/scan/summaries?market=US&source=fixture").json() == []
    assert client.get("/api/scan/summaries?market=CN&source=other").json() == []
    assert client.get("/api/scan/summaries?market=CN&source=fixture&adjustment=none").json() == []


def test_stock_profile_signal_sort_does_not_select_large_run_payloads(database):
    day = date(2025, 6, 20)
    save_bars(
        [
            BarInput(
                symbol="600000.SH",
                trade_date=day,
                source="fixture",
                adjustment="forward",
                open="10",
                high="11",
                low="9",
                close="10",
                volume="100",
            )
        ]
    )
    with session() as db, db.begin():
        for source, adjustment, target in [
            ("fixture", "forward", day),
            ("other", "forward", day),
            ("fixture", "none", day),
            ("fixture", "forward", date(2099, 1, 1)),
        ]:
            run = Run(
                kind="scan",
                market="CN",
                market_date=target,
                status="success",
                details={
                    "source": source,
                    "adjustment": adjustment,
                    "skipped": ["synthetic"] * 20000,
                },
            )
            db.add(run)
            db.flush()
            db.add(
                ScanResult(
                    run_id=run.id,
                    symbol="600000.SH",
                    trade_date=target,
                    hits=["box_breakout"],
                    close="10",
                    metadata_snapshot={},
                )
            )
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "scan_result" in statement and "ORDER BY" in statement:
            statements.append(statement)

    event.listen(database, "before_cursor_execute", record)
    try:
        client = TestClient(create_app())
        response = client.get(
            f"/api/stocks/600000.SH/profile?market=CN&source=fixture&endDate={day}"
        )
        signals = client.get(
            f"/api/stocks/600000.SH/signals?market=CN&source=fixture&endDate={day}"
        )
    finally:
        event.remove(database, "before_cursor_execute", record)
    assert response.status_code == signals.status_code == 200
    assert response.json()["latestScan"]["scanDate"] == str(day)
    assert [row["date"] for row in signals.json()] == [str(day)]
    assert len(statements) == 2
    assert all("job_run.details" not in statement.split("FROM")[0] for statement in statements)


def test_large_scan_log_stays_readable_under_small_mysql_sort_buffer(database):
    day = date(2025, 6, 20)
    with session() as db, db.begin():
        for index in range(2):
            db.add(
                Run(
                    kind="scan",
                    market="CN",
                    market_date=day,
                    status="partial",
                    started_at=now() - timedelta(seconds=index),
                    details={
                        "source": "large_fixture",
                        "adjustment": "forward",
                        "skipped": [{"symbol": "600000.SH", "reason": "low_liquidity"}] * 20000,
                    },
                )
            )

    def small_buffer(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            cursor.execute("SET SESSION sort_buffer_size = 32768")

    event.listen(database, "before_cursor_execute", small_buffer)
    try:
        client = TestClient(create_app())
        response = client.get("/api/scan/summaries?market=CN&source=large_fixture")
        detail = client.get(f"/api/scan/{day}/summary?market=CN&source=large_fixture")
    finally:
        event.remove(database, "before_cursor_execute", small_buffer)
    assert response.status_code == detail.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert rows[0]["executionDate"] > rows[1]["executionDate"]
    assert all(row["filteredOutCount"] == 20000 for row in rows)
    assert detail.json()["id"] == rows[0]["id"]


def test_daily_history_can_list_sources_together_but_details_keep_each_scope(database):
    with session() as db, db.begin():
        for market, source, adjustment, day in [
            ("CN", "first", "forward", date(2025, 6, 20)),
            ("CN", "second", "forward", date(2025, 6, 20)),
            ("CN", "first", "none", date(2025, 6, 20)),
            ("US", "second", "forward", date(2025, 6, 20)),
            ("CN", "second", "forward", date(2099, 1, 1)),
        ]:
            db.add(
                Run(
                    kind="scan",
                    market=market,
                    market_date=day,
                    status="success",
                    details={"source": source, "adjustment": adjustment},
                )
            )
    client = TestClient(create_app())
    assert len(client.get("/api/scan/summaries?market=CN&source=first").json()) == 1
    rows = client.get("/api/scan/summaries?market=CN&source=first&all_sources=true").json()
    assert {row["source"] for row in rows} == {"first", "second"}
    assert len(rows) == 2 and all(row["scanDate"] == "2025-06-20" for row in rows)
    for row in rows:
        assert (
            client.get(
                f"/api/scan/{row['id']}/summary?market=CN&source={row['source']}"
            ).status_code
            == 200
        )
        wrong = "second" if row["source"] == "first" else "first"
        assert (
            client.get(f"/api/scan/{row['id']}/summary?market=CN&source={wrong}").status_code == 404
        )


def test_tab_names_are_batched_without_account_or_price_data(database):
    with session() as db, db.begin():
        db.add_all(
            [
                Security(symbol="600000.SH", name="Synthetic CN", market="CN", currency="CNY"),
                Security(symbol="AAPL.US", name="Synthetic US", market="US", currency="USD"),
            ]
        )
    client = TestClient(create_app())
    response = client.get("/api/securities/names?symbols=600000.SH,AAPL.US,600001.SH")
    assert response.status_code == 200
    assert response.json() == {"600000.SH": "Synthetic CN", "AAPL.US": "Synthetic US"}
    assert (
        client.get(
            "/api/securities/names?symbols=" + ",".join(str(i) for i in range(11))
        ).status_code
        == 422
    )
