from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Date, ForeignKey, Numeric, String, Text, UniqueConstraint, text
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
    list_date: Mapped[date | None] = mapped_column(Date)


class DailyBar(Base):
    __tablename__ = "daily_bar"
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
    run_id: Mapped[str] = mapped_column(ForeignKey("job_run.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("security.symbol"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date)
    hits: Mapped[list[str]] = mapped_column(JSON)
    close: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    metadata_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)


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
