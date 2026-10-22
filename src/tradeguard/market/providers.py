"""A-share bar providers. Akshare is primary; baostock is the explicit fallback.

Network calls live on the provider objects so tests can substitute fakes.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Protocol

import pandas as pd
from pydantic import BaseModel, ConfigDict

from tradeguard.market.schemas import BarInput, normalize_symbol

BENCHMARK_SYMBOL = "000001.SH"
WARMUP_DAYS = 550


class ProviderOutage(RuntimeError):
    """The provider itself is unavailable. Callers may switch sources and must log it."""


class UniverseMember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    name: str
    is_st: bool = False
    list_date: date | None = None
    industry: str | None = None
    sector: str | None = None
    security_kind: str = "stock"


class BarProvider(Protocol):
    name: str

    def __enter__(self) -> BarProvider: ...

    def __exit__(self, exc_type, exc, tb) -> None: ...

    def trading_days(self, start: date, end: date) -> list[date]: ...

    def universe(self, as_of: date) -> list[UniverseMember]: ...

    def history(self, symbol: str, start: date, end: date) -> list[BarInput]: ...


class RateLimiter:
    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(0.0, min_interval)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            moment = time.monotonic()
            delay = max(0.0, self._next - moment)
            self._next = max(moment, self._next) + self.min_interval
        if delay:
            time.sleep(delay)


def _decimal(value: object, places: int = 4) -> Decimal:
    return Decimal(str(value)).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_EVEN)


def _as_date(value: object) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat", "--"}:
        return None
    text = text.replace("/", "-")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def exchange_of(code: str) -> str:
    if code.startswith(("43", "83", "87", "92", "8", "4")):
        return "BJ"
    if code.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def symbol_from_code(code: str) -> str:
    digits = "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)[-6:]
    return normalize_symbol(f"{digits}.{exchange_of(digits)}")


def parse_ak_hist(symbol: str, frame: pd.DataFrame, source: str = "akshare") -> list[BarInput]:
    """Eastmoney history via akshare. Volume is quoted in lots (手); store shares."""
    if frame is None or frame.empty:
        return []
    bars: list[BarInput] = []
    for row in frame.to_dict(orient="records"):
        trade_day = _as_date(row.get("日期"))
        close = row.get("收盘")
        if trade_day is None or close in (None, "") or pd.isna(close) or float(close) <= 0:
            continue
        open_ = _decimal(row.get("开盘") or close)
        high = _decimal(row.get("最高") or close)
        low = _decimal(row.get("最低") or close)
        close_d = _decimal(close)
        high = max(high, open_, close_d)
        low = min(low, open_, close_d)
        volume = _decimal(row.get("成交量") or 0, 4) * Decimal(100)
        amount_raw = row.get("成交额")
        amount = None if amount_raw is None or pd.isna(amount_raw) else _decimal(amount_raw, 4)
        try:
            bars.append(
                BarInput(
                    symbol=symbol,
                    trade_date=trade_day,
                    source=source,
                    adjustment="forward",
                    open=open_,
                    high=high,
                    low=low,
                    close=close_d,
                    volume=volume,
                    amount=amount,
                )
            )
        except ValueError:
            continue
    return bars


def _outage(exc: BaseException) -> bool:
    name = type(exc).__name__
    return isinstance(exc, (ConnectionError, TimeoutError, OSError, ImportError)) or name in {
        "ConnectionError",
        "Timeout",
        "ConnectTimeout",
        "ReadTimeout",
        "RemoteDisconnected",
        "ChunkedEncodingError",
        "HTTPError",
        "RequestException",
        "SSLError",
    }


def _guard(call: Callable[[], object]):
    try:
        return call()
    except ProviderOutage:
        raise
    except Exception as exc:
        if _outage(exc):
            raise ProviderOutage(f"{type(exc).__name__}: {exc}") from exc
        raise


class AkshareProvider:
    name = "akshare"

    def __init__(self, min_interval: float = 0.2) -> None:
        self.limiter = RateLimiter(min_interval)
        self.warnings: list[str] = []

    def __enter__(self) -> AkshareProvider:
        try:
            import akshare as ak
        except ImportError as exc:
            raise ProviderOutage("akshare is not installed; uv sync --extra market") from exc
        self._ak = ak
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def trading_days(self, start: date, end: date) -> list[date]:
        frame = _guard(lambda: self._ak.tool_trade_date_hist_sina())
        assert isinstance(frame, pd.DataFrame)
        column = "trade_date" if "trade_date" in frame.columns else frame.columns[0]
        days = []
        for value in frame[column]:
            day = _as_date(value)
            if day is not None and start <= day <= end:
                days.append(day)
        return sorted(set(days))

    def universe(self, as_of: date) -> list[UniverseMember]:
        del as_of
        names = _guard(lambda: self._ak.stock_info_a_code_name())
        assert isinstance(names, pd.DataFrame)
        st_codes = self._st_codes()
        industries = self._industries()
        listings = self._listings()
        members: list[UniverseMember] = []
        seen: set[str] = set()
        code_col = "code" if "code" in names.columns else "代码"
        name_col = "name" if "name" in names.columns else "名称"
        for row in names.to_dict(orient="records"):
            try:
                symbol = symbol_from_code(str(row.get(code_col, "")))
            except ValueError:
                continue
            if not symbol.endswith((".SH", ".SZ", ".BJ")) or symbol in seen:
                continue
            seen.add(symbol)
            label = str(row.get(name_col) or symbol)
            industry = industries.get(symbol)
            members.append(
                UniverseMember(
                    symbol=symbol,
                    name=label,
                    is_st=symbol in st_codes or "ST" in label.upper(),
                    list_date=listings.get(symbol),
                    industry=industry,
                    sector=industry,
                )
            )
        if not members:
            raise ProviderOutage("akshare returned an empty A-share universe")
        return members

    def history(self, symbol: str, start: date, end: date) -> list[BarInput]:
        if start > end:
            return []
        self.limiter.wait()
        if symbol == BENCHMARK_SYMBOL:
            frame = _guard(
                lambda: self._ak.index_zh_a_hist(
                    symbol="000001",
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                )
            )
        else:
            code = symbol.split(".")[0]
            frame = _guard(
                lambda: self._ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                )
            )
        assert isinstance(frame, pd.DataFrame)
        return parse_ak_hist(symbol, frame, source=self.name)

    def _st_codes(self) -> set[str]:
        try:
            self.limiter.wait()
            frame = self._ak.stock_zh_a_st_em()
        except Exception as exc:
            self.warnings.append(f"st_list_unavailable:{type(exc).__name__}")
            return set()
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return set()
        column = "代码" if "代码" in frame.columns else frame.columns[0]
        codes = set()
        for value in frame[column]:
            try:
                codes.add(symbol_from_code(str(value)))
            except ValueError:
                continue
        return codes

    def _listings(self) -> dict[str, date]:
        found: dict[str, date] = {}
        calls: tuple[tuple[str, dict[str, str]], ...] = (
            ("stock_info_sh_name_code", {"symbol": "主板A股"}),
            ("stock_info_sh_name_code", {"symbol": "科创板"}),
            ("stock_info_sz_name_code", {"symbol": "A股列表"}),
            ("stock_info_bj_name_code", {}),
        )
        for name, kwargs in calls:
            fn = getattr(self._ak, name, None)
            if fn is None:
                continue
            try:
                self.limiter.wait()
                frame = fn(**kwargs) if kwargs else fn()
            except Exception as exc:
                self.warnings.append(f"list_date_unavailable:{name}:{type(exc).__name__}")
                continue
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                continue
            code_col = next(
                (c for c in frame.columns if "代码" in str(c) or str(c).lower() == "code"),
                frame.columns[0],
            )
            date_col = next((c for c in frame.columns if "上市" in str(c)), None)
            if date_col is None:
                continue
            for row in frame.to_dict(orient="records"):
                try:
                    symbol = symbol_from_code(str(row.get(code_col, "")))
                except ValueError:
                    continue
                listed = _as_date(row.get(date_col))
                if listed is not None:
                    found[symbol] = listed
        return found

    def _industries(self) -> dict[str, str]:
        try:
            self.limiter.wait()
            boards = self._ak.stock_board_industry_name_em()
        except Exception as exc:
            self.warnings.append(f"industry_unavailable:{type(exc).__name__}")
            return {}
        if not isinstance(boards, pd.DataFrame) or boards.empty:
            return {}
        name_col = "板块名称" if "板块名称" in boards.columns else boards.columns[0]
        found: dict[str, str] = {}
        for board in boards[name_col].tolist():
            try:
                self.limiter.wait()
                cons = self._ak.stock_board_industry_cons_em(symbol=str(board))
            except Exception as exc:
                self.warnings.append(f"industry_board_failed:{board}:{type(exc).__name__}")
                continue
            if not isinstance(cons, pd.DataFrame) or cons.empty:
                continue
            code_col = "代码" if "代码" in cons.columns else cons.columns[0]
            for value in cons[code_col].tolist():
                try:
                    found.setdefault(symbol_from_code(str(value)), str(board))
                except ValueError:
                    continue
        return found


def _bs_symbol(symbol: str) -> str:
    code, exch = symbol.split(".")
    return f"{exch.lower()}.{code}"


class BaostockProvider:
    name = "baostock"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def __enter__(self) -> BaostockProvider:
        try:
            import baostock as bs
        except ImportError as exc:
            raise ProviderOutage("baostock is not installed; uv sync --extra market") from exc
        import contextlib
        import sys

        self._bs = bs
        with contextlib.redirect_stdout(sys.stderr):
            login = bs.login()
        if getattr(login, "error_code", "1") != "0":
            raise ProviderOutage("baostock login failed")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        import contextlib
        import sys

        with contextlib.redirect_stdout(sys.stderr):
            self._bs.logout()
        return None

    def _rows(self, result) -> list[dict]:
        if result.error_code != "0":
            raise ProviderOutage(f"baostock query failed: {result.error_code}")
        rows = []
        while result.next():
            rows.append(dict(zip(result.fields, result.get_row_data(), strict=True)))
        if result.error_code != "0":
            raise ProviderOutage("baostock stream failed")
        return rows

    def trading_days(self, start: date, end: date) -> list[date]:
        rows = self._rows(self._bs.query_trade_dates(start_date=str(start), end_date=str(end)))
        return sorted(
            date.fromisoformat(row["calendar_date"])
            for row in rows
            if row.get("is_trading_day") == "1"
        )

    def universe(self, as_of: date) -> list[UniverseMember]:
        rows = self._rows(self._bs.query_all_stock(day=str(as_of)))
        industries = self._industry_map()
        listings = self._listing_map()
        members: list[UniverseMember] = []
        seen: set[str] = set()
        for row in rows:
            code = row.get("code", "")
            if not code.startswith(("sh.6", "sz.0", "sz.3", "bj.4", "bj.8", "bj.9")):
                continue
            try:
                symbol = normalize_symbol(f"{code.split('.')[1]}.{code.split('.')[0].upper()}")
            except ValueError:
                continue
            if symbol in seen:
                continue
            seen.add(symbol)
            label = row.get("code_name") or symbol
            industry = industries.get(symbol)
            members.append(
                UniverseMember(
                    symbol=symbol,
                    name=label,
                    is_st="ST" in label.upper(),
                    list_date=listings.get(symbol),
                    industry=industry,
                    sector=industry,
                )
            )
        if not members:
            raise ProviderOutage("baostock returned an empty A-share universe")
        return members

    def history(self, symbol: str, start: date, end: date) -> list[BarInput]:
        if start > end:
            return []
        rows = self._rows(
            self._bs.query_history_k_data_plus(
                _bs_symbol(symbol),
                "date,open,high,low,close,volume,amount",
                start_date=str(start),
                end_date=str(end),
                frequency="d",
                adjustflag="2",
            )
        )
        bars: list[BarInput] = []
        for row in rows:
            if not row.get("close"):
                continue
            try:
                bars.append(
                    BarInput(
                        symbol=symbol,
                        trade_date=row["date"],
                        source=self.name,
                        adjustment="forward",
                        open=row["open"],
                        high=row["high"],
                        low=row["low"],
                        close=row["close"],
                        volume=_decimal(str(row.get("volume") or "0"), 4),
                        amount=_decimal(str(row["amount"]), 4) if row.get("amount") else None,
                    )
                )
            except ValueError:
                continue
        return bars

    def _industry_map(self) -> dict[str, str]:
        try:
            rows = self._rows(self._bs.query_stock_industry())
        except ProviderOutage as exc:
            self.warnings.append(f"industry_unavailable:{exc}")
            return {}
        found = {}
        for row in rows:
            code = row.get("code") or ""
            if "." not in code:
                continue
            try:
                symbol = normalize_symbol(f"{code.split('.')[1]}.{code.split('.')[0].upper()}")
            except ValueError:
                continue
            industry = row.get("industry") or None
            if industry:
                found[symbol] = industry
        return found

    def _listing_map(self) -> dict[str, date]:
        try:
            rows = self._rows(self._bs.query_stock_basic())
        except ProviderOutage as exc:
            self.warnings.append(f"list_date_unavailable:{exc}")
            return {}
        found = {}
        for row in rows:
            code = row.get("code") or ""
            if "." not in code:
                continue
            try:
                symbol = normalize_symbol(f"{code.split('.')[1]}.{code.split('.')[0].upper()}")
            except ValueError:
                continue
            listed = _as_date(row.get("ipoDate"))
            if listed is not None:
                found[symbol] = listed
        return found
