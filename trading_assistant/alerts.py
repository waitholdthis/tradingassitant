"""Watchlist alerts: declarative rules evaluated against an OHLCV series."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .data import OHLCV
from . import indicators as ind


@dataclass
class Alert:
    symbol: str
    rule: str
    message: str


class AlertRule(ABC):
    @abstractmethod
    def check(self, series: OHLCV) -> Alert | None:
        """Return an Alert if the rule fires on the latest bar, else None."""


@dataclass
class PriceAbove(AlertRule):
    level: float

    def check(self, series: OHLCV) -> Alert | None:
        if not series.bars:
            return None
        close = series.bars[-1].close
        if close > self.level:
            return Alert(series.symbol, f"price_above({self.level:g})",
                         f"{series.symbol} closed at {close:.2f}, above {self.level:g}")
        return None


@dataclass
class PriceBelow(AlertRule):
    level: float

    def check(self, series: OHLCV) -> Alert | None:
        if not series.bars:
            return None
        close = series.bars[-1].close
        if close < self.level:
            return Alert(series.symbol, f"price_below({self.level:g})",
                         f"{series.symbol} closed at {close:.2f}, below {self.level:g}")
        return None


@dataclass
class RsiThreshold(AlertRule):
    """Fires when RSI is beyond a threshold (oversold if ``below`` else overbought)."""

    threshold: float = 30.0
    below: bool = True
    period: int = 14

    def check(self, series: OHLCV) -> Alert | None:
        values = ind.rsi(series.closes, self.period)
        if not values or values[-1] is None:
            return None
        v = values[-1]
        if self.below and v < self.threshold:
            return Alert(series.symbol, f"rsi_below({self.threshold:g})",
                         f"{series.symbol} RSI({self.period}) = {v:.1f}, oversold (< {self.threshold:g})")
        if not self.below and v > self.threshold:
            return Alert(series.symbol, f"rsi_above({self.threshold:g})",
                         f"{series.symbol} RSI({self.period}) = {v:.1f}, overbought (> {self.threshold:g})")
        return None


@dataclass
class SmaCross(AlertRule):
    """Fires on the bar where the fast SMA crosses the slow SMA."""

    fast: int = 20
    slow: int = 50

    def check(self, series: OHLCV) -> Alert | None:
        closes = series.closes
        if len(closes) < self.slow + 1:
            return None
        fast, slow = ind.sma(closes, self.fast), ind.sma(closes, self.slow)
        prev_diff = fast[-2] - slow[-2]
        cur_diff = fast[-1] - slow[-1]
        if prev_diff <= 0 < cur_diff:
            return Alert(series.symbol, f"sma_cross_up({self.fast},{self.slow})",
                         f"{series.symbol} SMA{self.fast} crossed above SMA{self.slow} (bullish)")
        if prev_diff >= 0 > cur_diff:
            return Alert(series.symbol, f"sma_cross_down({self.fast},{self.slow})",
                         f"{series.symbol} SMA{self.fast} crossed below SMA{self.slow} (bearish)")
        return None


@dataclass
class VolumeSpike(AlertRule):
    """Fires when the latest volume exceeds ``multiple`` x its trailing average."""

    multiple: float = 2.0
    period: int = 20

    def check(self, series: OHLCV) -> Alert | None:
        vols = series.volumes
        if len(vols) < self.period + 1:
            return None
        avg = sum(vols[-self.period - 1 : -1]) / self.period
        if avg > 0 and vols[-1] > avg * self.multiple:
            return Alert(series.symbol, f"volume_spike({self.multiple:g}x)",
                         f"{series.symbol} volume {vols[-1]:,.0f} is {vols[-1] / avg:.1f}x its {self.period}-day average")
        return None


class Watchlist:
    """A set of rules per symbol, evaluated in one pass."""

    def __init__(self) -> None:
        self.rules: dict[str, list[AlertRule]] = {}

    def add(self, symbol: str, rule: AlertRule) -> None:
        self.rules.setdefault(symbol.upper(), []).append(rule)

    def evaluate(self, data: dict[str, OHLCV]) -> list[Alert]:
        alerts = []
        for symbol, rules in self.rules.items():
            series = data.get(symbol)
            if series is None:
                continue
            for rule in rules:
                alert = rule.check(series)
                if alert:
                    alerts.append(alert)
        return alerts
