"""Technical indicators.

All functions take plain sequences of floats and return lists aligned to the
input: positions before the indicator has enough data are ``None``. Smoothed
indicators (RSI, ATR) use Wilder's smoothing, matching standard charting
platforms.
"""

from __future__ import annotations

from typing import NamedTuple, Sequence

Series = list  # list[float | None]


def sma(values: Sequence[float], period: int) -> Series:
    """Simple moving average."""
    _check(values, period)
    out: Series = [None] * len(values)
    window_sum = 0.0
    for i, v in enumerate(values):
        window_sum += v
        if i >= period:
            window_sum -= values[i - period]
        if i >= period - 1:
            out[i] = window_sum / period
    return out


def ema(values: Sequence[float], period: int) -> Series:
    """Exponential moving average, seeded with the SMA of the first window."""
    _check(values, period)
    out: Series = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def wma(values: Sequence[float], period: int) -> Series:
    """Linearly weighted moving average."""
    _check(values, period)
    out: Series = [None] * len(values)
    denom = period * (period + 1) / 2
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        out[i] = sum(w * v for w, v in zip(range(1, period + 1), window)) / denom
    return out


def rsi(values: Sequence[float], period: int = 14) -> Series:
    """Relative Strength Index (Wilder)."""
    _check(values, period)
    out: Series = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


class MACD(NamedTuple):
    macd: Series
    signal: Series
    histogram: Series


def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal_period: int = 9) -> MACD:
    """MACD line, signal line, and histogram."""
    if fast >= slow:
        raise ValueError(f"fast period ({fast}) must be < slow period ({slow})")
    fast_ema, slow_ema = ema(values, fast), ema(values, slow)
    line: Series = [
        f - s if f is not None and s is not None else None for f, s in zip(fast_ema, slow_ema)
    ]
    valid_start = next((i for i, v in enumerate(line) if v is not None), len(line))
    sig: Series = [None] * len(values)
    valid = line[valid_start:]
    if valid:
        sig[valid_start:] = ema(valid, signal_period)
    hist: Series = [
        m - s if m is not None and s is not None else None for m, s in zip(line, sig)
    ]
    return MACD(line, sig, hist)


class BollingerBands(NamedTuple):
    upper: Series
    middle: Series
    lower: Series


def bollinger(values: Sequence[float], period: int = 20, num_std: float = 2.0) -> BollingerBands:
    """Bollinger Bands around an SMA."""
    middle = sma(values, period)
    upper: Series = [None] * len(values)
    lower: Series = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        mean = middle[i]
        std = (sum((v - mean) ** 2 for v in window) / period) ** 0.5
        upper[i] = mean + num_std * std
        lower[i] = mean - num_std * std
    return BollingerBands(upper, middle, lower)


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> Series:
    """True range; first element is simply high - low."""
    out: Series = [highs[0] - lows[0]] if highs else []
    for i in range(1, len(highs)):
        out.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    return out


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> Series:
    """Average True Range (Wilder)."""
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows, closes must be the same length")
    _check(closes, period)
    tr = true_range(highs, lows, closes)
    out: Series = [None] * len(closes)
    if len(closes) < period:
        return out
    prev = sum(tr[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(closes)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


class Stochastic(NamedTuple):
    k: Series
    d: Series


def stochastic(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    k_period: int = 14,
    d_period: int = 3,
) -> Stochastic:
    """Stochastic oscillator %K and %D."""
    _check(closes, k_period)
    k: Series = [None] * len(closes)
    for i in range(k_period - 1, len(closes)):
        hh = max(highs[i - k_period + 1 : i + 1])
        ll = min(lows[i - k_period + 1 : i + 1])
        k[i] = 50.0 if hh == ll else 100.0 * (closes[i] - ll) / (hh - ll)
    valid_start = k_period - 1
    d: Series = [None] * len(closes)
    valid = k[valid_start:]
    if valid:
        d[valid_start:] = sma(valid, d_period)
    return Stochastic(k, d)


def obv(closes: Sequence[float], volumes: Sequence[float]) -> Series:
    """On-balance volume."""
    out: Series = [0.0] * len(closes)
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            out[i] = out[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            out[i] = out[i - 1] - volumes[i]
        else:
            out[i] = out[i - 1]
    return out


def vwap(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
) -> Series:
    """Cumulative volume-weighted average price."""
    out: Series = [None] * len(closes)
    cum_pv = cum_v = 0.0
    for i in range(len(closes)):
        typical = (highs[i] + lows[i] + closes[i]) / 3.0
        cum_pv += typical * volumes[i]
        cum_v += volumes[i]
        out[i] = cum_pv / cum_v if cum_v > 0 else typical
    return out


def roc(values: Sequence[float], period: int = 12) -> Series:
    """Rate of change, in percent."""
    _check(values, period)
    out: Series = [None] * len(values)
    for i in range(period, len(values)):
        if values[i - period] != 0:
            out[i] = 100.0 * (values[i] - values[i - period]) / values[i - period]
    return out


def rolling_max(values: Sequence[float], period: int) -> Series:
    _check(values, period)
    out: Series = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = max(values[i - period + 1 : i + 1])
    return out


def rolling_min(values: Sequence[float], period: int) -> Series:
    _check(values, period)
    out: Series = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = min(values[i - period + 1 : i + 1])
    return out


def _check(values: Sequence[float], period: int) -> None:
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
