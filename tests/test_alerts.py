from datetime import date, timedelta

from trading_assistant.alerts import (
    PriceAbove,
    PriceBelow,
    RsiThreshold,
    SmaCross,
    VolumeSpike,
    Watchlist,
)
from trading_assistant.data import OHLCV, Bar, synthetic_series


def flat_series(price: float, days: int, last_volume: float | None = None) -> OHLCV:
    bars = []
    d = date(2025, 1, 1)
    for i in range(days):
        vol = last_volume if (last_volume and i == days - 1) else 1000.0
        bars.append(Bar(d, price, price, price, price, vol))
        d += timedelta(days=1)
    return OHLCV("FLAT", bars)


def test_price_above_fires_only_past_level():
    s = flat_series(105.0, 5)
    assert PriceAbove(100.0).check(s) is not None
    assert PriceAbove(110.0).check(s) is None


def test_price_below():
    s = flat_series(95.0, 5)
    assert PriceBelow(100.0).check(s) is not None
    assert PriceBelow(90.0).check(s) is None


def test_rsi_oversold_fires_after_decline():
    bars = []
    d = date(2025, 1, 1)
    price = 200.0
    for _ in range(30):
        nxt = price * 0.98
        bars.append(Bar(d, price, price, nxt, nxt, 1000))
        price = nxt
        d += timedelta(days=1)
    s = OHLCV("DOWN", bars)
    alert = RsiThreshold(threshold=30, below=True).check(s)
    assert alert is not None
    assert "oversold" in alert.message


def test_volume_spike():
    s = flat_series(100.0, 30, last_volume=5000.0)
    alert = VolumeSpike(multiple=2.0, period=20).check(s)
    assert alert is not None
    s2 = flat_series(100.0, 30)
    assert VolumeSpike(multiple=2.0, period=20).check(s2) is None


def test_sma_cross_needs_actual_cross():
    # A series long enough but flat never crosses.
    s = flat_series(100.0, 60)
    assert SmaCross(5, 20).check(s) is None


def test_watchlist_evaluates_all_rules():
    wl = Watchlist()
    wl.add("flat", PriceAbove(50.0))
    wl.add("FLAT", PriceBelow(50.0))
    wl.add("MISSING", PriceAbove(1.0))
    alerts = wl.evaluate({"FLAT": flat_series(100.0, 5)})
    assert len(alerts) == 1
    assert alerts[0].symbol == "FLAT"
    assert "above 50" in alerts[0].message


def test_rules_handle_short_series():
    short = synthetic_series(days=3, seed=1)
    for rule in [RsiThreshold(), SmaCross(), VolumeSpike()]:
        assert rule.check(short) is None
