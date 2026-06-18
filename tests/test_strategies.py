import pytest

from trading_assistant.data import synthetic_series
from trading_assistant.strategies import (
    BollingerBreakout,
    DonchianBreakout,
    EnsembleStrategy,
    MacdMomentum,
    RsiMeanReversion,
    Signal,
    SmaCrossover,
    make_strategy,
)

SERIES = synthetic_series(days=300, seed=7)

ALL_STRATEGIES = [
    SmaCrossover(),
    RsiMeanReversion(),
    MacdMomentum(),
    BollingerBreakout(),
    DonchianBreakout(),
]


@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=lambda s: s.name)
def test_signal_length_matches_series(strategy):
    assert len(strategy.signals(SERIES)) == len(SERIES)


@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=lambda s: s.name)
def test_warmup_emits_none_then_real_signals(strategy):
    signals = strategy.signals(SERIES)
    assert signals[0] is Signal.NONE
    assert any(s is not Signal.NONE for s in signals)


@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=lambda s: s.name)
def test_signals_are_causal(strategy):
    """Signals on a prefix must match signals on the full series (no look-ahead)."""
    full = strategy.signals(SERIES)
    cut = 200
    prefix = strategy.signals(type(SERIES)(SERIES.symbol, SERIES.bars[:cut]))
    assert prefix == full[:cut]


def test_sma_crossover_validates_periods():
    with pytest.raises(ValueError):
        SmaCrossover(fast=50, slow=20)


def test_rsi_validates_thresholds():
    with pytest.raises(ValueError):
        RsiMeanReversion(oversold=60, exit_level=40)


def test_sma_crossover_goes_long_in_steady_uptrend():
    up = synthetic_series(days=300, drift=0.005, volatility=0.001, seed=1)
    signals = SmaCrossover(fast=10, slow=30).signals(up)
    assert signals[-1] is Signal.LONG


def test_ensemble_majority_vote():
    ensemble = EnsembleStrategy(ALL_STRATEGIES)
    signals = ensemble.signals(SERIES)
    member_signals = [s.signals(SERIES) for s in ALL_STRATEGIES]
    for i, sig in enumerate(signals):
        votes = [m[i] for m in member_signals if m[i] is not Signal.NONE]
        if not votes:
            assert sig is Signal.NONE
        else:
            longs = sum(1 for v in votes if v is Signal.LONG)
            expected = Signal.LONG if longs >= len(votes) // 2 + 1 else Signal.FLAT
            assert sig is expected


def test_ensemble_requires_members():
    with pytest.raises(ValueError):
        EnsembleStrategy([])


def test_make_strategy_factory():
    assert make_strategy("sma").name.startswith("sma_cross")
    assert make_strategy("ensemble").name.startswith("ensemble")
    with pytest.raises(ValueError, match="unknown strategy"):
        make_strategy("hodl")
