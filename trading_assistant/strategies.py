"""Signal-generating strategies.

A strategy converts an OHLCV series into a list of :class:`Signal` values, one
per bar: ``LONG`` (be invested), ``FLAT`` (be in cash), or ``NONE`` (no
opinion / warm-up). Strategies only ever look at data up to and including the
current bar, so signals are free of look-ahead bias by construction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from .data import OHLCV
from . import indicators as ind


class Signal(Enum):
    NONE = 0
    LONG = 1
    FLAT = 2


class Strategy(ABC):
    """Base class. Subclasses implement :meth:`signals`."""

    name: str = "strategy"

    @abstractmethod
    def signals(self, series: OHLCV) -> list[Signal]:
        """Return one signal per bar in ``series``."""

    def describe(self) -> str:
        return self.name


class SmaCrossover(Strategy):
    """Long when the fast SMA is above the slow SMA, flat otherwise."""

    def __init__(self, fast: int = 20, slow: int = 50):
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be < slow ({slow})")
        self.fast, self.slow = fast, slow
        self.name = f"sma_cross({fast},{slow})"

    def signals(self, series: OHLCV) -> list[Signal]:
        closes = series.closes
        fast, slow = ind.sma(closes, self.fast), ind.sma(closes, self.slow)
        out = []
        for f, s in zip(fast, slow):
            if f is None or s is None:
                out.append(Signal.NONE)
            else:
                out.append(Signal.LONG if f > s else Signal.FLAT)
        return out


class RsiMeanReversion(Strategy):
    """Buy oversold (RSI below ``oversold``), exit when RSI recovers past ``exit_level``."""

    def __init__(self, period: int = 14, oversold: float = 30.0, exit_level: float = 55.0):
        if not 0 < oversold < exit_level <= 100:
            raise ValueError("require 0 < oversold < exit_level <= 100")
        self.period, self.oversold, self.exit_level = period, oversold, exit_level
        self.name = f"rsi_revert({period},{oversold:g},{exit_level:g})"

    def signals(self, series: OHLCV) -> list[Signal]:
        values = ind.rsi(series.closes, self.period)
        out: list[Signal] = []
        holding = False
        for v in values:
            if v is None:
                out.append(Signal.NONE)
            elif not holding and v < self.oversold:
                holding = True
                out.append(Signal.LONG)
            elif holding and v > self.exit_level:
                holding = False
                out.append(Signal.FLAT)
            else:
                out.append(Signal.LONG if holding else Signal.FLAT)
        return out


class MacdMomentum(Strategy):
    """Long while the MACD line is above its signal line."""

    def __init__(self, fast: int = 12, slow: int = 26, signal_period: int = 9):
        self.fast, self.slow, self.signal_period = fast, slow, signal_period
        self.name = f"macd({fast},{slow},{signal_period})"

    def signals(self, series: OHLCV) -> list[Signal]:
        m = ind.macd(series.closes, self.fast, self.slow, self.signal_period)
        out = []
        for line, sig in zip(m.macd, m.signal):
            if line is None or sig is None:
                out.append(Signal.NONE)
            else:
                out.append(Signal.LONG if line > sig else Signal.FLAT)
        return out


class BollingerBreakout(Strategy):
    """Enter on a close above the upper band; exit on a close below the middle band."""

    def __init__(self, period: int = 20, num_std: float = 2.0):
        self.period, self.num_std = period, num_std
        self.name = f"boll_break({period},{num_std:g})"

    def signals(self, series: OHLCV) -> list[Signal]:
        closes = series.closes
        bands = ind.bollinger(closes, self.period, self.num_std)
        out: list[Signal] = []
        holding = False
        for c, up, mid in zip(closes, bands.upper, bands.middle):
            if up is None:
                out.append(Signal.NONE)
                continue
            if not holding and c > up:
                holding = True
            elif holding and c < mid:
                holding = False
            out.append(Signal.LONG if holding else Signal.FLAT)
        return out


class DonchianBreakout(Strategy):
    """Classic channel breakout: enter on an N-bar high, exit on an M-bar low."""

    def __init__(self, entry_period: int = 55, exit_period: int = 20):
        self.entry_period, self.exit_period = entry_period, exit_period
        self.name = f"donchian({entry_period},{exit_period})"

    def signals(self, series: OHLCV) -> list[Signal]:
        highs = ind.rolling_max(series.highs, self.entry_period)
        lows = ind.rolling_min(series.lows, self.exit_period)
        closes = series.closes
        out: list[Signal] = []
        holding = False
        for i, c in enumerate(closes):
            # Compare against the prior bar's channel so today's bar can't
            # trigger on a level it created itself.
            hi = highs[i - 1] if i > 0 else None
            lo = lows[i - 1] if i > 0 else None
            if hi is None or lo is None:
                out.append(Signal.NONE)
                continue
            if not holding and c > hi:
                holding = True
            elif holding and c < lo:
                holding = False
            out.append(Signal.LONG if holding else Signal.FLAT)
        return out


class EnsembleStrategy(Strategy):
    """Combine member strategies by vote.

    Goes long when at least ``min_agree`` members (default: a strict majority
    of those with an opinion) say LONG.
    """

    def __init__(self, members: list[Strategy], min_agree: int | None = None):
        if not members:
            raise ValueError("ensemble needs at least one member strategy")
        self.members = members
        self.min_agree = min_agree
        self.name = f"ensemble[{', '.join(m.name for m in members)}]"

    def signals(self, series: OHLCV) -> list[Signal]:
        all_signals = [m.signals(series) for m in self.members]
        out: list[Signal] = []
        for i in range(len(series)):
            votes = [s[i] for s in all_signals if s[i] is not Signal.NONE]
            if not votes:
                out.append(Signal.NONE)
                continue
            needed = self.min_agree if self.min_agree is not None else len(votes) // 2 + 1
            longs = sum(1 for v in votes if v is Signal.LONG)
            out.append(Signal.LONG if longs >= needed else Signal.FLAT)
        return out


BUILTIN_STRATEGIES = {
    "sma": SmaCrossover,
    "rsi": RsiMeanReversion,
    "macd": MacdMomentum,
    "bollinger": BollingerBreakout,
    "donchian": DonchianBreakout,
}


def make_strategy(name: str) -> Strategy:
    """Create a built-in strategy by name with default parameters.

    ``"ensemble"`` builds a majority vote of all built-in strategies.
    """
    if name == "ensemble":
        return EnsembleStrategy([cls() for cls in BUILTIN_STRATEGIES.values()])
    try:
        return BUILTIN_STRATEGIES[name]()
    except KeyError:
        options = ", ".join([*BUILTIN_STRATEGIES, "ensemble"])
        raise ValueError(f"unknown strategy {name!r}; choose from: {options}") from None
