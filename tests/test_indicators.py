import math

import pytest

from trading_assistant import indicators as ind


class TestSma:
    def test_basic(self):
        assert ind.sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]

    def test_period_one_is_identity(self):
        assert ind.sma([5.0, 7.0], 1) == [5.0, 7.0]

    def test_insufficient_data(self):
        assert ind.sma([1, 2], 5) == [None, None]

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            ind.sma([1, 2, 3], 0)


class TestEma:
    def test_seeded_with_sma(self):
        out = ind.ema([1, 2, 3, 4, 5], 3)
        assert out[:2] == [None, None]
        assert out[2] == 2.0  # seed = SMA of first 3
        # alpha = 0.5: 0.5*4 + 0.5*2 = 3.0, then 0.5*5 + 0.5*3 = 4.0
        assert out[3] == 3.0
        assert out[4] == 4.0

    def test_constant_series(self):
        out = ind.ema([10.0] * 20, 5)
        assert all(v == 10.0 for v in out[4:])


class TestRsi:
    def test_all_gains_is_100(self):
        out = ind.rsi(list(range(1, 30)), 14)
        assert out[14] == 100.0

    def test_bounds(self):
        prices = [100 + ((-1) ** i) * (i % 7) for i in range(60)]
        for v in ind.rsi(prices, 14):
            if v is not None:
                assert 0.0 <= v <= 100.0

    def test_known_value(self):
        # Standard worked RSI example (Wilder)
        prices = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
                  45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        out = ind.rsi(prices, 14)
        assert out[14] == pytest.approx(70.46, abs=0.1)


class TestMacd:
    def test_histogram_is_macd_minus_signal(self):
        prices = [100 + math.sin(i / 5) * 10 + i * 0.1 for i in range(120)]
        m = ind.macd(prices)
        for line, sig, hist in zip(m.macd, m.signal, m.histogram):
            if hist is not None:
                assert hist == pytest.approx(line - sig)

    def test_fast_must_be_less_than_slow(self):
        with pytest.raises(ValueError):
            ind.macd([1.0] * 50, fast=26, slow=12)


class TestBollinger:
    def test_band_ordering(self):
        prices = [100 + math.sin(i / 3) * 5 for i in range(60)]
        bands = ind.bollinger(prices, 20)
        for up, mid, lo in zip(bands.upper, bands.middle, bands.lower):
            if up is not None:
                assert lo <= mid <= up

    def test_constant_series_collapses(self):
        bands = ind.bollinger([50.0] * 30, 20)
        assert bands.upper[-1] == bands.middle[-1] == bands.lower[-1] == 50.0


class TestAtr:
    def test_positive_and_warmup(self):
        n = 40
        highs = [102.0 + i * 0.1 for i in range(n)]
        lows = [98.0 + i * 0.1 for i in range(n)]
        closes = [100.0 + i * 0.1 for i in range(n)]
        out = ind.atr(highs, lows, closes, 14)
        assert out[12] is None
        assert out[13] is not None
        assert all(v > 0 for v in out[13:])

    def test_length_mismatch(self):
        with pytest.raises(ValueError):
            ind.atr([1, 2], [1], [1, 2], 1)


class TestStochastic:
    def test_bounds(self):
        highs = [100 + (i % 10) for i in range(50)]
        lows = [h - 2 for h in highs]
        closes = [h - 1 for h in highs]
        st = ind.stochastic(highs, lows, closes)
        for k in st.k:
            if k is not None:
                assert 0.0 <= k <= 100.0

    def test_flat_range_returns_midpoint(self):
        st = ind.stochastic([10.0] * 20, [10.0] * 20, [10.0] * 20, 14)
        assert st.k[-1] == 50.0


class TestObvVwap:
    def test_obv_direction(self):
        closes = [10, 11, 10, 10]
        vols = [100, 200, 300, 400]
        assert ind.obv(closes, vols) == [0.0, 200.0, -100.0, -100.0]

    def test_vwap_between_low_and_high(self):
        highs, lows = [102.0, 104.0], [98.0, 100.0]
        closes, vols = [100.0, 102.0], [1000.0, 1000.0]
        out = ind.vwap(highs, lows, closes, vols)
        assert min(lows) <= out[-1] <= max(highs)


class TestRoc:
    def test_basic(self):
        out = ind.roc([100, 100, 110], 2)
        assert out == [None, None, pytest.approx(10.0)]
