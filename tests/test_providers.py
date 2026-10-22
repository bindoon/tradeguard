from datetime import date

import pandas as pd

from tradeguard.db.maintenance import legacy_run_filter_sql, legacy_run_is_in_progress
from tradeguard.market.providers import parse_ak_hist, symbol_from_code
from tradeguard.pipeline import select_scan_dates


def test_akshare_volume_is_converted_from_lots_to_shares():
    frame = pd.DataFrame(
        [
            {
                "日期": "2026-06-25",
                "开盘": 10,
                "收盘": 10.5,
                "最高": 10.6,
                "最低": 9.9,
                "成交量": 10,
                "成交额": 100000,
            }
        ]
    )
    bars = parse_ak_hist("600000.SH", frame)
    assert len(bars) == 1
    assert bars[0].volume == 1000
    assert bars[0].source == "akshare"
    assert bars[0].adjustment == "forward"
    assert bars[0].trade_date == date(2026, 6, 25)


def test_symbol_prefixes():
    assert symbol_from_code("600000") == "600000.SH"
    assert symbol_from_code("sz000001") == "000001.SZ"
    assert symbol_from_code("300001") == "300001.SZ"
    assert symbol_from_code("830001") == "830001.BJ"


def test_scan_dates_backfill_then_skip_completed_days():
    calendar = [date(2026, 6, 24), date(2026, 6, 25), date(2026, 6, 26)]
    assert select_scan_dates(
        calendar,
        target=None,
        start=None,
        end=None,
        anchor=date(2026, 6, 25),
        completed=set(),
        force=False,
    ) == [date(2026, 6, 26)]
    assert (
        select_scan_dates(
            calendar,
            target=None,
            start=None,
            end=None,
            anchor=date(2026, 6, 26),
            completed={date(2026, 6, 26)},
            force=False,
        )
        == []
    )
    assert select_scan_dates(
        calendar,
        target=date(2026, 6, 25),
        start=None,
        end=None,
        anchor=date(2026, 6, 26),
        completed={date(2026, 6, 25)},
        force=True,
    ) == [date(2026, 6, 25)]


def test_legacy_running_rows_are_not_a_lock():
    assert legacy_run_is_in_progress("running") is False
    assert legacy_run_is_in_progress("pending") is False
    assert "running" in legacy_run_filter_sql()
    assert "pending" in legacy_run_filter_sql()
