from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Date, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from tradeguard.db.types import UTCDateTime


def now() -> datetime:
    return datetime.now(timezone.utc)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "job_run"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="running")
    market: Mapped[str | None] = mapped_column(String(8), index=True)
    market_date: Mapped[date | None] = mapped_column(Date, index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Security(Base):
    __tablename__ = "security"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    market: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(3))
    industry: Mapped[str | None] = mapped_column(String(100))
    sector: Mapped[str | None] = mapped_column(String(100))
    list_date: Mapped[date | None] = mapped_column(Date)
    is_st: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    security_kind: Mapped[str] = mapped_column(String(16), default="stock", server_default="stock")


class DailyBar(Base):
    __tablename__ = "daily_bar"
    __table_args__ = (
        Index("ix_daily_bar_source_adjustment_date", "source", "adjustment", "trade_date"),
    )
    symbol: Mapped[str] = mapped_column(ForeignKey("security.symbol"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    adjustment: Mapped[str] = mapped_column(String(16), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    high: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    low: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    close: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    volume: Mapped[Decimal] = mapped_column(Numeric(30, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class ScanResult(Base):
    __tablename__ = "scan_result"
    __table_args__ = (Index("ix_scan_result_symbol_trade_date", "symbol", "trade_date"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("job_run.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("security.symbol"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date)
    hits: Mapped[list[str]] = mapped_column(JSON)
    close: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    resonance_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    sector_strength: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    metadata_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class ScanSummary(Base):
    """One row per market day and bar source. Rescans update this row in place."""

    __tablename__ = "scan_summary"
    __table_args__ = (
        UniqueConstraint(
            "market", "trade_date", "source", "adjustment", name="uq_scan_summary_day"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("job_run.id"), index=True)
    market: Mapped[str] = mapped_column(String(8))
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(40))
    adjustment: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20))
    market_regime: Mapped[str] = mapped_column(String(20), default="unknown")
    benchmark: Mapped[str | None] = mapped_column(String(32))
    universe_count: Mapped[int] = mapped_column(default=0)
    scanned_count: Mapped[int] = mapped_column(default=0)
    hit_count: Mapped[int] = mapped_column(default=0)
    resonance_count: Mapped[int] = mapped_column(default=0)
    strategy_hit_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sector_strength: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    filter_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Account(Base):
    __tablename__ = "account"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    broker: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(100))


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshot"
    __table_args__ = (UniqueConstraint("account_id", "external_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(100))
    as_of: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    recorded_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=now, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class RuleProfile(Base):
    __tablename__ = "rule_profile"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(60), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    rules: Mapped[dict[str, Any]] = mapped_column(JSON)


class DisciplineCheck(Base):
    __tablename__ = "discipline_check"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    rule_profile_id: Mapped[str] = mapped_column(ForeignKey("rule_profile.id"))
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("portfolio_snapshot.id"))
    intent: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)


class ResearchReport(Base):
    __tablename__ = "research_report"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class RunEvent(Base):
    __tablename__ = "run_event"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("job_run.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    stage: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    completed: Mapped[int | None]
    total: Mapped[int | None]
