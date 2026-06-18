"""Position sizing and stop management."""

from __future__ import annotations

from dataclasses import dataclass


def fixed_fractional_size(
    equity: float, price: float, risk_fraction: float = 0.02, stop_distance: float | None = None
) -> int:
    """Shares to buy risking ``risk_fraction`` of equity.

    With a ``stop_distance`` (entry price minus stop price), risk is measured
    to the stop; otherwise the full position value counts as at-risk capital.
    """
    _check_positive(equity=equity, price=price)
    if not 0 < risk_fraction <= 1:
        raise ValueError(f"risk_fraction must be in (0, 1], got {risk_fraction}")
    risk_capital = equity * risk_fraction
    per_share = stop_distance if stop_distance and stop_distance > 0 else price
    shares = int(risk_capital / per_share)
    return min(shares, int(equity / price))  # never exceed buying power


def atr_position_size(
    equity: float, price: float, atr_value: float, risk_fraction: float = 0.01, atr_multiple: float = 2.0
) -> int:
    """Volatility-adjusted sizing: stop is assumed ``atr_multiple`` ATRs away."""
    _check_positive(equity=equity, price=price, atr_value=atr_value)
    return fixed_fractional_size(equity, price, risk_fraction, stop_distance=atr_value * atr_multiple)


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float, cap: float = 0.25) -> float:
    """Kelly-optimal bet fraction, capped (full Kelly is wildly aggressive).

    ``avg_win`` and ``avg_loss`` are average win/loss amounts (both positive).
    Returns 0 when the edge is non-positive.
    """
    if not 0 <= win_rate <= 1:
        raise ValueError(f"win_rate must be in [0, 1], got {win_rate}")
    if avg_win <= 0 or avg_loss <= 0:
        return 0.0
    payoff = avg_win / avg_loss
    kelly = win_rate - (1 - win_rate) / payoff
    return max(0.0, min(kelly, cap))


@dataclass
class StopLevels:
    stop_loss: float
    take_profit: float


def bracket(entry: float, stop_pct: float = 0.05, reward_risk: float = 2.0) -> StopLevels:
    """Stop-loss and take-profit around an entry at a fixed reward:risk ratio."""
    _check_positive(entry=entry, stop_pct=stop_pct, reward_risk=reward_risk)
    risk = entry * stop_pct
    return StopLevels(stop_loss=entry - risk, take_profit=entry + risk * reward_risk)


def atr_bracket(entry: float, atr_value: float, stop_mult: float = 2.0, reward_risk: float = 2.0) -> StopLevels:
    """ATR-based stop-loss and take-profit."""
    _check_positive(entry=entry, atr_value=atr_value)
    risk = atr_value * stop_mult
    return StopLevels(stop_loss=entry - risk, take_profit=entry + risk * reward_risk)


class TrailingStop:
    """Ratchet stop that follows the highest price seen since entry."""

    def __init__(self, entry: float, trail_pct: float = 0.08):
        _check_positive(entry=entry, trail_pct=trail_pct)
        self.highest = entry
        self.trail_pct = trail_pct

    @property
    def stop(self) -> float:
        return self.highest * (1 - self.trail_pct)

    def update(self, price: float) -> bool:
        """Feed the latest price; returns True when the stop is hit."""
        if price > self.highest:
            self.highest = price
        return price <= self.stop


def max_drawdown(equity_curve: list[float]) -> float:
    """Largest peak-to-trough decline as a fraction (0.25 = -25%)."""
    peak = float("-inf")
    worst = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak)
    return worst


def _check_positive(**kwargs: float) -> None:
    for name, value in kwargs.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive, got {value}")
