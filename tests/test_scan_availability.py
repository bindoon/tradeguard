"""The scan console must expose real cached dates and find existing scan history."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tradeguard.console import create_app
from tradeguard.db import session
from tradeguard.db.models import Run, Security, now
from tradeguard.market.schemas import BarInput
from tradeguard.market.service import save_bars


def bar(symbol, day, source="baostock", adjustment="forward"):
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


def test_default_source_follows_latest_saved_scan_without_combining_sources(database):
    old, recent = date(2025, 1, 20), date(2025, 6, 20)
    save_bars([bar("600000.SH", old, "legacy_mysql"), bar("600000.SH", recent)])
    with session() as db, db.begin():
        db.add_all(
            [
                Run(
                    kind="scan",
                    market="CN",
                    market_date=recent,
                    status="partial",
                    details={"source": "baostock", "adjustment": "forward"},
                ),
                Run(
                    kind="scan",
                    market="CN",
                    market_date=old,
                    status="success",
                    started_at=now() + timedelta(seconds=1),
                    details={"source": "legacy_mysql", "adjustment": "forward"},
                ),
            ]
        )
    client = TestClient(create_app())
    context = client.get("/api/context?market=CN").json()
    assert context["default_source"] == "baostock"
    assert context["default_adjustment"] == "forward"
    activity = {s["source"]: s for s in context["sources"]}
    assert activity["baostock"]["latest_scan_date"] == str(recent)
    assert activity["baostock"]["scan_count"] == 1
    assert activity["legacy_mysql"]["latest_scan_date"] == str(old)
    # A user who explicitly chooses the imported history still sees that scope only.
    rows = client.get("/api/scan/summaries?market=CN&source=legacy_mysql").json()
    assert len(rows) == 1 and rows[0]["source"] == "legacy_mysql"


def test_scan_dates_only_include_cached_equities_in_requested_scope(database):
    day, earlier = date(2025, 6, 20), date(2025, 6, 19)
    save_bars(
        [
            bar("600000.SH", day),
            bar("600519.SH", day),
            bar("600000.SH", earlier),
            bar("600000.SH", date(2025, 6, 18), "legacy_mysql"),
            bar("600000.SH", date(2025, 6, 17), adjustment="none"),
            bar("AAPL.US", date(2025, 6, 16)),
            bar("000001.SH", date(2025, 6, 15)),
            bar("600000.SH", date(2099, 1, 1)),
        ]
    )
    with session() as db, db.begin():
        db.get(Security, "000001.SH").security_kind = "index"
    client = TestClient(create_app())
    response = client.get("/api/scan/dates?market=CN&source=baostock&adjustment=forward")
    assert response.status_code == 200
    assert response.json() == [
        {"date": str(day), "symbols": 2},
        {"date": str(earlier), "symbols": 1},
    ]
    assert client.get("/api/scan/dates?market=HK&source=baostock").json() == []
    assert client.get("/api/scan/dates?market=CN&source=missing").json() == []
    raw = client.get("/api/scan/dates?market=CN&source=baostock&adjustment=none").json()
    assert raw == [{"date": "2025-06-17", "symbols": 1}]


def test_empty_scan_is_rejected_before_a_background_job_is_created(database):
    day = date(2025, 6, 20)
    save_bars([bar("600000.SH", day), bar("600519.SH", day, "legacy_mysql")])
    client = TestClient(create_app())
    with session() as db:
        before = db.scalar(select(func.count()).select_from(Run))
    for scope in [
        {"date": "2025-06-21", "market": "CN", "source": "baostock"},
        {"date": str(day), "market": "CN", "source": "baostock", "adjustment": "none"},
        {"date": str(day), "market": "US", "source": "baostock"},
        {"date": str(day), "market": "CN", "source": "baostock", "symbols": ["600519.SH"]},
    ]:
        response = client.post("/api/scan/run", json=scope)
        assert response.status_code == 422
        assert "缓存" in response.json()["detail"]
    with session() as db:
        assert db.scalar(select(func.count()).select_from(Run)) == before
        assert db.scalar(select(func.count()).select_from(Run).where(Run.kind == "scan")) == 0


def test_small_market_context_is_empty_until_its_own_bars_are_saved(database):
    day = date(2025, 6, 20)
    save_bars([bar("600000.SH", day)])
    with session() as db, db.begin():
        db.add_all(
            [
                Security(symbol="00700.HK", name="Synthetic HK", market="HK", currency="HKD"),
                Security(symbol="AAPL.US", name="Synthetic US", market="US", currency="USD"),
            ]
        )
    client = TestClient(create_app())
    for market, symbol, currency in [("HK", "00700.HK", "HKD"), ("US", "AAPL.US", "USD")]:
        before = client.get("/api/context", params={"market": market}).json()
        assert before["security_count"] == 1
        assert before["currency"] == currency
        assert before["sources"] == []
        assert before["default_source"] == ""
        save_bars([bar(symbol, day)])
        after = client.get("/api/context", params={"market": market}).json()
        assert after["sources"] == [
            {
                "source": "baostock",
                "adjustment": "forward",
                "rows": 1,
                "symbols": 1,
                "min_date": str(day),
                "max_date": str(day),
                "scan_count": 0,
                "latest_scan_date": None,
            }
        ]
