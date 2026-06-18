"""One-shot technical snapshot of a symbol: trend, momentum, volatility."""

from __future__ import annotations

from dataclasses import dataclass

from .data import OHLCV
from . import indicators as ind


@dataclass
class Snapshot:
    symbol: str
    close: float
    change_pct: float
    sma20: float | None
    sma50: float | None
    sma200: float | None
    rsi14: float | None
    macd_hist: float | None
    atr14: float | None
    bb_position: float | None  # 0 = lower band, 1 = upper band
    high_52w: float | None
    low_52w: float | None

    @property
    def trend(self) -> str:
        if self.sma50 is None:
            return "unknown"
        above50 = self.close > self.sma50
        if self.sma200 is not None:
            above200 = self.close > self.sma200
            if above50 and above200:
                return "uptrend"
            if not above50 and not above200:
                return "downtrend"
            return "mixed"
        return "uptrend" if above50 else "downtrend"

    @property
    def momentum(self) -> str:
        if self.rsi14 is None:
            return "unknown"
        if self.rsi14 >= 70:
            return "overbought"
        if self.rsi14 <= 30:
            return "oversold"
        return "neutral"

    def report(self) -> str:
        def fmt(v: float | None, spec: str = ".2f") -> str:
            return format(v, spec) if v is not None else "n/a"

        lines = [
            f"{self.symbol}  close {self.close:.2f}  ({self.change_pct:+.2%} on the day)",
            f"  Trend:     {self.trend}  "
            f"[SMA20 {fmt(self.sma20)}, SMA50 {fmt(self.sma50)}, SMA200 {fmt(self.sma200)}]",
            f"  Momentum:  {self.momentum}  [RSI(14) {fmt(self.rsi14, '.1f')}, MACD hist {fmt(self.macd_hist, '.3f')}]",
            f"  Volatility: ATR(14) {fmt(self.atr14)}"
            + (f" ({self.atr14 / self.close:.1%} of price)" if self.atr14 else ""),
            f"  Bollinger: {fmt(self.bb_position, '.0%')} of band range" if self.bb_position is not None else "  Bollinger: n/a",
            f"  52w range: {fmt(self.low_52w)} - {fmt(self.high_52w)}"
            + (
                f"  ({(self.close - self.low_52w) / (self.high_52w - self.low_52w):.0%} of range)"
                if self.high_52w and self.low_52w and self.high_52w > self.low_52w
                else ""
            ),
        ]
        return "\n".join(lines)


def snapshot(series: OHLCV) -> Snapshot:
    if len(series) < 2:
        raise ValueError(f"need at least 2 bars to analyze, got {len(series)}")
    closes, highs, lows = series.closes, series.highs, series.lows

    def last(values: list) -> float | None:
        return values[-1] if values else None

    sma20 = last(ind.sma(closes, 20)) if len(closes) >= 20 else None
    sma50 = last(ind.sma(closes, 50)) if len(closes) >= 50 else None
    sma200 = last(ind.sma(closes, 200)) if len(closes) >= 200 else None
    rsi14 = last(ind.rsi(closes, 14)) if len(closes) > 14 else None
    macd_hist = last(ind.macd(closes).histogram) if len(closes) >= 35 else None
    atr14 = last(ind.atr(highs, lows, closes, 14)) if len(closes) >= 14 else None

    bb_position = None
    if len(closes) >= 20:
        bands = ind.bollinger(closes, 20)
        up, lo = bands.upper[-1], bands.lower[-1]
        if up is not None and lo is not None and up > lo:
            bb_position = (closes[-1] - lo) / (up - lo)

    return Snapshot(
        symbol=series.symbol,
        close=closes[-1],
        change_pct=closes[-1] / closes[-2] - 1.0,
        sma20=sma20,
        sma50=sma50,
        sma200=sma200,
        rsi14=rsi14,
        macd_hist=macd_hist,
        atr14=atr14,
        bb_position=bb_position,
        high_52w=max(highs[-252:]) if len(closes) >= 20 else None,
        low_52w=min(lows[-252:]) if len(closes) >= 20 else None,
    )
