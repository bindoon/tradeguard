"""Optional baostock provider; each invocation owns a serial SDK session."""

import contextlib
import socket
import sys
from datetime import date

from tradeguard.market.schemas import BarInput, normalize_symbol
from tradeguard.market.service import save_bars


@contextlib.contextmanager
def _socket_timeout():
    # baostock creates a process-global socket without a timeout. This provider is
    # serial and CLI-only; never run it concurrently inside an HTTP process.
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(15)
    try:
        yield
    finally:
        socket.setdefaulttimeout(previous)


def _rows(result) -> list[dict]:
    if result.error_code != "0":
        raise RuntimeError(f"baostock query failed: {result.error_code}")
    rows = []
    while result.next():
        rows.append(dict(zip(result.fields, result.get_row_data(), strict=True)))
    if result.error_code != "0":
        raise RuntimeError("baostock stream failed")
    return rows


def sync(target: date, start: date, symbols: list[str] | None = None) -> dict:
    if start > target:
        raise ValueError("start must not exceed target date")
    try:
        import baostock as bs
    except ImportError as e:
        raise ValueError("Install market dependencies: uv sync --extra market") from e
    # The SDK prints login/logout messages. Preserve stdout for the CLI JSON contract.
    with _socket_timeout(), contextlib.redirect_stdout(sys.stderr):
        login = bs.login()
        if login.error_code != "0":
            raise RuntimeError("baostock login failed")
        try:
            calendar = _rows(bs.query_trade_dates(start_date=str(target), end_date=str(target)))
            if len(calendar) != 1 or calendar[0]["is_trading_day"] != "1":
                raise ValueError("Target is not a verified trading day")
            universe = _rows(bs.query_all_stock(day=str(target)))
            universe = [r for r in universe if r["code"].startswith(("sh.6", "sz.0", "sz.3"))]
            by_symbol = {normalize_symbol(r["code"]): r for r in universe}
            selected = [normalize_symbol(s) for s in symbols] if symbols else list(by_symbol)
            if not selected or len(selected) != len(set(selected)):
                raise ValueError("Stock universe is empty or contains duplicates")
            failed, saved, stale = [], 0, []
            for symbol in selected:
                if symbol not in by_symbol:
                    failed.append({"symbol": symbol, "reason": "not_in_universe"})
                    continue
                code = by_symbol[symbol]["code"]
                try:
                    rows = _rows(
                        bs.query_history_k_data_plus(
                            code,
                            "date,open,high,low,close,volume,amount",
                            start_date=str(start),
                            end_date=str(target),
                            frequency="d",
                            adjustflag="2",
                        )
                    )
                    bars = [
                        BarInput(
                            symbol=symbol,
                            name=by_symbol[symbol].get("code_name", symbol),
                            trade_date=r["date"],
                            source="baostock",
                            adjustment="forward",
                            **{
                                k: r[k]
                                for k in ("open", "high", "low", "close", "volume", "amount")
                            },
                        )
                        for r in rows
                        if r.get("close")
                    ]
                    result = save_bars(bars)
                    saved += result["rows"]
                    if max(b.trade_date for b in bars) != target:
                        stale.append(symbol)
                except (ValueError, RuntimeError) as e:
                    failed.append({"symbol": symbol, "reason": type(e).__name__})
            return {
                "date": str(target),
                "requested": len(selected),
                "rows": saved,
                "failed": failed,
                "stale": stale,
                "source": "baostock",
                "status": "partial" if failed or stale else "success",
                "adjustment": "forward",
                "refreshed_from": str(start),
            }
        finally:
            bs.logout()
