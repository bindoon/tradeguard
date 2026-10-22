from datetime import date, timedelta
from types import SimpleNamespace

from tradeguard.screening.filters import FilterOptions, rejection


def bars(
    days: int = 70, *, close: float = 10, volume: float = 1_000_000, amount: float = 200_000_000
):
    start = date(2024, 1, 2)
    rows = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        rows.append(
            {
                "trade_date": day,
                "open": close,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": volume,
                "amount": amount,
            }
        )
    return rows


def security(**kwargs):
    payload = {
        "symbol": "600000.SH",
        "name": "测试银行",
        "is_st": False,
        "list_date": date(2010, 1, 4),
    }
    payload.update(kwargs)
    return SimpleNamespace(**payload)


def test_prefilter_matches_selection_thresholds():
    target = bars()[-1]["trade_date"]
    options = FilterOptions.for_market("CN")
    assert rejection(security(), bars(), target, "CN", options)[0] is None

    assert rejection(security(name="ST测试"), bars(), target, "CN", options)[0] == "st_stock"
    assert (
        rejection(security(name="测试", is_st=True), bars(), target, "CN", options)[0] == "st_stock"
    )
    recent = security(list_date=target - timedelta(days=10))
    assert rejection(recent, bars(), target, "CN", options)[0] == "recent_listing"
    assert (
        rejection(security(), bars(volume=0), target, "CN", options)[0]
        == "suspended_or_zero_volume"
    )
    assert rejection(security(), bars(amount=1_000), target, "CN", options)[0] == "low_liquidity"

    limited = bars()
    limited[-1]["close"] = 11
    limited[-1]["high"] = 11.2
    assert rejection(security(), limited, target, "CN", options)[0] == "limit_move"

    growth = bars()
    growth[-1]["close"] = 11
    growth[-1]["high"] = 11.2
    assert rejection(security(symbol="300001.SZ"), growth, target, "CN", options)[0] is None
    growth[-1]["close"] = 12.1
    growth[-1]["high"] = 12.2
    assert rejection(security(symbol="300001.SZ"), growth, target, "CN", options)[0] == "limit_move"
