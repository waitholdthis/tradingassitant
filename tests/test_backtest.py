import pytest

from trading_assistant.backtest import Backtester, buy_and_hold
from trading_assistant.data import OHLCV, Bar, synthetic_series
from trading_assistant.strategies import Signal, SmaCrossover, Strategy


class AlwaysLong(Strategy):
    name = "always_long"

    def signals(self, series):
        return [Signal.LONG] * len(series)


class NeverTrade(Strategy):
    name = "never_trade"

    def signals(self, series):
        return [Signal.FLAT] * len(series)


SERIES = synthetic_series(days=300, seed=11)


def test_never_trading_preserves_capital():
    result = Backtester(initial_capital=50_000).run(NeverTrade(), SERIES)
    assert result.final_equity == 50_000
    assert result.trades == []
    assert result.total_return == 0.0


def test_signals_execute_next_open():
    result = Backtester(commission=0.0, slippage_bps=0.0).run(AlwaysLong(), SERIES)
    # First signal is on bar 0, so the entry fills at bar 1's open.
    assert result.trades[0].entry_date == SERIES.bars[1].date
    assert result.trades[0].entry_price == pytest.approx(SERIES.bars[1].open)


def test_equity_curve_alignment():
    result = Backtester().run(SmaCrossover(), SERIES)
    assert len(result.equity_curve) == len(SERIES)
    assert result.dates == SERIES.dates


def test_costs_reduce_returns():
    cheap = Backtester(commission=0.0, slippage_bps=0.0).run(SmaCrossover(), SERIES)
    costly = Backtester(commission=10.0, slippage_bps=50.0).run(SmaCrossover(), SERIES)
    assert costly.final_equity < cheap.final_equity


def test_trades_close_when_signal_flips():
    result = Backtester().run(SmaCrossover(), SERIES)
    for t in result.trades[:-1]:
        assert not t.is_open
        assert t.exit_date > t.entry_date


def test_buy_and_hold_matches_price_change():
    result = buy_and_hold(SERIES, initial_capital=100_000)
    entry = SERIES.bars[1].open
    shares = int(100_000 * 0.95 / entry)
    expected = 100_000 - shares * entry + shares * SERIES.bars[-1].close
    assert result.final_equity == pytest.approx(expected)


def test_metrics_on_known_curve():
    from datetime import date, timedelta

    bars = []
    prices = [100, 110, 99, 120, 108]
    d = date(2025, 1, 6)
    for p in prices:
        bars.append(Bar(d, p, p, p, p, 1000))
        d += timedelta(days=1)
    series = OHLCV("X", bars)
    result = buy_and_hold(series, initial_capital=10_000)
    # Drawdown of the price path: peak 120 -> 108 = 10%
    assert result.max_drawdown == pytest.approx(0.10, abs=0.01)


def test_win_rate_and_profit_factor_bounds():
    result = Backtester().run(SmaCrossover(), SERIES)
    assert 0.0 <= result.win_rate <= 1.0
    assert result.profit_factor >= 0.0
    assert 0.0 <= result.exposure <= 1.0


def test_rejects_too_short_series():
    short = OHLCV("X", SERIES.bars[:1])
    with pytest.raises(ValueError):
        Backtester().run(AlwaysLong(), short)


def test_rejects_bad_config():
    with pytest.raises(ValueError):
        Backtester(initial_capital=-1)
    with pytest.raises(ValueError):
        Backtester(position_fraction=1.5)
