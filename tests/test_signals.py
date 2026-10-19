import pandas as pd

from tradeguard.screening.strategies.bollinger_breakout import STRATEGY


def test_bollinger_first_volume_breakout_and_no_low_volume_signal():
    # Frozen synthetic scenario: 29 flat closes followed by a large price/volume break.
    frame = pd.DataFrame({"close": [100.0] * 29 + [120.0], "volume": [1000.0] * 29 + [10000.0]})
    result = STRATEGY.screen("600000.SH", "synthetic", frame, "2026-01-30")
    assert result is not None and result["latest_price"] == 120.0
    quiet = frame.copy()
    quiet.loc[29, "volume"] = 100.0
    assert STRATEGY.screen("600000.SH", "synthetic", quiet, "2026-01-30") is None
