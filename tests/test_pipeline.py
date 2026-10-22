from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from tradeguard.cli import app
from tradeguard.db.maintenance import retire_stale_runs
from tradeguard.db.models import DailyBar, Run, RunEvent, ScanSummary, now
from tradeguard.market.providers import ProviderOutage, UniverseMember
from tradeguard.market.schemas import BarInput
from tradeguard.pipeline import run_cn_pipeline
from tradeguard.report import daily_report
from tradeguard.screening.service import scan


class Hit:
    def __init__(self, name: str):
        self.name = name
        self.title = name
        self.description = "fixture reason"

    def screen(self, **kwargs):
        if kwargs["result_date"] != self.only:
            return None
        return {"metadata": {"fixture": self.name}}


class Miss:
    name = "bollinger_breakout"
    title = "布林"
    description = "未命中"

    def screen(self, **kwargs):
        return None


class FakeProvider:
    def __init__(self, name: str, fail: str | None = None):
        self.name = name
        self.fail = fail
        self.history_calls: list[tuple[str, date, date]] = []
        self.entered = 0

    def __enter__(self):
        self.entered += 1
        if self.fail == "enter":
            raise ProviderOutage("akshare down")
        return self

    def __exit__(self, *args):
        return None

    def trading_days(self, start: date, end: date) -> list[date]:
        if self.fail == "calendar":
            raise ProviderOutage("calendar down")
        days = []
        cursor = start
        while cursor <= end:
            if cursor.weekday() < 5:
                days.append(cursor)
            cursor += timedelta(days=1)
        return days

    def universe(self, as_of: date) -> list[UniverseMember]:
        del as_of
        return [
            UniverseMember(
                symbol="600000.SH",
                name="测试银行",
                is_st=False,
                list_date=date(2010, 1, 4),
                industry="银行",
                sector="银行",
            )
        ]

    def history(self, symbol: str, start: date, end: date) -> list[BarInput]:
        self.history_calls.append((symbol, start, end))
        if self.fail == "history" and symbol != "000001.SH":
            raise RuntimeError("symbol failed")
        cursor = end
        days: list[date] = []
        while len(days) < 70:
            if cursor.weekday() < 5:
                days.append(cursor)
            cursor -= timedelta(days=1)
        days.reverse()
        return [
            BarInput(
                symbol=symbol,
                name="上证指数" if symbol == "000001.SH" else "测试银行",
                trade_date=day,
                source=self.name,
                adjustment="forward",
                open=Decimal("10"),
                high=Decimal("10.2"),
                low=Decimal("9.8"),
                close=Decimal("10"),
                volume=Decimal("1000000"),
                amount=Decimal("200000000"),
            )
            for day in days
        ]


def _run(primary: FakeProvider, fallback: FakeProvider | None = None, **kwargs):
    moment = datetime(2026, 6, 30, 3, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    return run_cn_pipeline(
        primary=primary,
        fallback=fallback,
        allow_fallback=fallback is not None,
        workers=1,
        min_interval=0,
        now_local=moment,
        **kwargs,
    )


def test_backfill_is_idempotent_and_records_source(database):
    primary = FakeProvider("akshare")
    fallback = FakeProvider("baostock")
    first = _run(primary, fallback)
    assert first["status"] == "success", first
    assert first["source"] == "akshare"
    assert first["fallback"] is None
    assert {symbol for symbol, _, _ in primary.history_calls} == {"600000.SH", "000001.SH"}
    assert fallback.entered == 0
    with Session(database) as db:
        rows = db.scalar(select(func.count()).select_from(DailyBar))
        summary = db.scalar(select(ScanSummary).where(ScanSummary.source == "akshare"))
    assert rows and rows > 0
    assert summary is not None and summary.market_regime in {"bull", "bear", "neutral"}
    calls = len(primary.history_calls)
    second = _run(primary, fallback)
    assert second["up_to_date"] is True
    assert second["status"] == "success"
    assert len(primary.history_calls) == calls
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(DailyBar)) == rows


def test_provider_outage_falls_back_and_logs_the_switch(database):
    primary = FakeProvider("akshare", fail="calendar")
    fallback = FakeProvider("baostock")
    result = _run(primary, fallback)
    assert result["source"] == "baostock"
    assert result["fallback"]["from"] == "akshare"
    assert result["fallback"]["to"] == "baostock"
    with Session(database) as db:
        stages = db.scalars(select(RunEvent.stage).where(RunEvent.run_id == result["run_id"])).all()
        sources = set(db.scalars(select(DailyBar.source)).all())
    assert "source_fallback" in stages
    assert sources == {"baostock"}


def test_symbol_failure_stays_partial_without_switching_source(database):
    primary = FakeProvider("akshare", fail="history")
    fallback = FakeProvider("baostock")
    result = _run(primary, fallback)
    assert result["status"] == "partial"
    assert result["source"] == "akshare"
    assert result["fallback"] is None
    assert fallback.entered == 0
    assert any(item["symbol"] == "600000.SH" for item in result["failed"])


def test_stale_job_does_not_block_the_next_run(database):
    with Session(database) as db, db.begin():
        stale = Run(
            kind="daily",
            market="CN",
            status="running",
            started_at=now() - timedelta(hours=7),
            details={},
        )
        fresh = Run(kind="scan", market="CN", status="running", started_at=now(), details={})
        db.add(stale)
        db.add(fresh)
        db.flush()
        stale_id, fresh_id = stale.id, fresh.id
    retired = retire_stale_runs()
    assert stale_id in retired
    with Session(database) as db:
        assert db.get(Run, stale_id).status == "stale"
        assert db.get(Run, fresh_id).status == "running"
    result = _run(FakeProvider("akshare"), FakeProvider("baostock"))
    assert result["status"] == "success"


def test_resonance_report_and_day_over_day_changes(database, monkeypatch):
    from pathlib import Path

    from tradeguard.market.service import import_csv

    import_csv(Path("examples/bars.csv"))
    with Session(database) as db:
        days = list(
            db.scalars(select(DailyBar.trade_date).distinct().order_by(DailyBar.trade_date)).all()
        )
    earlier, later = days[-2], days[-1]
    hit_a = Hit("ma_golden_cross")
    hit_b = Hit("macd_golden_cross")
    hit_a.only = str(later)
    hit_b.only = str(later)

    def strategies(selected=None):
        del selected
        return [hit_a, hit_b, Miss()]

    monkeypatch.setattr("tradeguard.screening.service.get_registered_strategies", strategies)
    first = scan(earlier, "synthetic", symbols=["600000.SH"])
    second = scan(later, "synthetic", symbols=["600000.SH"])
    assert first["resonance_count"] == 0
    assert second["resonance_count"] == 1
    assert second["candidates"][0]["hits"] == ["ma_golden_cross", "macd_golden_cross"]
    report = daily_report(later, "CN", "synthetic")
    assert report["market_regime"] in {"bull", "bear", "neutral", "unknown"}
    assert report["counts"]["resonance"] == 1
    assert report["counts"]["per_strategy"]["ma_golden_cross"] == 1
    assert report["top_resonance"][0]["symbol"] == "600000.SH"
    assert report["top_resonance"][0]["resonance_count"] == 2
    assert any("fixture reason" in reason for reason in report["top_resonance"][0]["reasons"])
    assert report["changes_vs_previous_day"]["previous_date"] == str(earlier)
    assert report["changes_vs_previous_day"]["new_symbols"][0]["symbol"] == "600000.SH"
    assert report["sector_strength_ranking"]


def test_cn_daily_cli_uses_the_backfill_pipeline(monkeypatch):
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return {"status": "success", "source": "akshare"}

    monkeypatch.setattr("tradeguard.jobs.run_cn_pipeline", fake)
    result = CliRunner().invoke(
        app, ["pipeline", "daily", "--market", "CN", "--from", "2026-06-26", "--to", "2026-06-29"]
    )
    assert result.exit_code == 0, result.output
    assert captured["start"] == date(2026, 6, 26)
    assert captured["end"] == date(2026, 6, 29)
    blocked = CliRunner().invoke(
        app,
        [
            "pipeline",
            "daily",
            "--market",
            "CN",
            "--date",
            "2026-06-26",
            "--from",
            "2026-06-26",
            "--to",
            "2026-06-29",
        ],
    )
    assert blocked.exit_code == 1
