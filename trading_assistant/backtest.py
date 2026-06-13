"""Event-driven backtester.

Signals computed on bar *t* are executed at the *open of bar t+1* (no
look-ahead), with configurable commission and slippage. Produces an equity
curve, trade list, and standard performance metrics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from .data import OHLCV
from .strategies import Signal, Strategy
from .risk import max_drawdown

TRADING_DAYS = 252


@dataclass
class Trade:
    symbol: str
    entry_date: date
    entry_price: float
    shares: int
    exit_date: date | None = None
    exit_price: float | None = None

    @property
    def is_open(self) -> bool:
        return self.exit_date is None

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.shares

    @property
    def return_pct(self) -> float:
        if self.exit_price is None:
            return 0.0
        return self.exit_price / self.entry_price - 1.0


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    initial_capital: float
    equity_curve: list[float]
    dates: list[date]
    trades: list[Trade]

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1] if self.equity_curve else self.initial_capital

    @property
    def total_return(self) -> float:
        return self.final_equity / self.initial_capital - 1.0

    @property
    def cagr(self) -> float:
        if len(self.dates) < 2 or self.final_equity <= 0:
            return 0.0
        years = (self.dates[-1] - self.dates[0]).days / 365.25
        if years <= 0:
            return 0.0
        return (self.final_equity / self.initial_capital) ** (1 / years) - 1.0

    @property
    def daily_returns(self) -> list[float]:
        return [
            self.equity_curve[i] / self.equity_curve[i - 1] - 1.0
            for i in range(1, len(self.equity_curve))
            if self.equity_curve[i - 1] > 0
        ]

    @property
    def sharpe(self) -> float:
        """Annualized Sharpe ratio (0% risk-free rate)."""
        r = self.daily_returns
        if len(r) < 2:
            return 0.0
        mean = sum(r) / len(r)
        var = sum((x - mean) ** 2 for x in r) / (len(r) - 1)
        std = math.sqrt(var)
        if std == 0:
            return 0.0
        return mean / std * math.sqrt(TRADING_DAYS)

    @property
    def sortino(self) -> float:
        """Annualized Sortino ratio (downside deviation only)."""
        r = self.daily_returns
        if len(r) < 2:
            return 0.0
        mean = sum(r) / len(r)
        downside = [x for x in r if x < 0]
        if not downside:
            return float("inf") if mean > 0 else 0.0
        dd = math.sqrt(sum(x**2 for x in downside) / len(r))
        if dd == 0:
            return 0.0
        return mean / dd * math.sqrt(TRADING_DAYS)

    @property
    def max_drawdown(self) -> float:
        return max_drawdown(self.equity_curve)

    @property
    def closed_trades(self) -> list[Trade]:
        return [t for t in self.trades if not t.is_open]

    @property
    def win_rate(self) -> float:
        closed = self.closed_trades
        if not closed:
            return 0.0
        return sum(1 for t in closed if t.pnl > 0) / len(closed)

    @property
    def profit_factor(self) -> float:
        wins = sum(t.pnl for t in self.closed_trades if t.pnl > 0)
        losses = -sum(t.pnl for t in self.closed_trades if t.pnl < 0)
        if losses == 0:
            return float("inf") if wins > 0 else 0.0
        return wins / losses

    @property
    def exposure(self) -> float:
        """Fraction of bars spent in the market."""
        if not self.dates:
            return 0.0
        in_market = 0
        open_spans = [
            (t.entry_date, t.exit_date or self.dates[-1]) for t in self.trades
        ]
        for d in self.dates:
            if any(start <= d <= end for start, end in open_spans):
                in_market += 1
        return in_market / len(self.dates)

    def summary(self) -> str:
        lines = [
            f"Backtest: {self.strategy} on {self.symbol}",
            f"  Period:        {self.dates[0]} to {self.dates[-1]}" if self.dates else "  Period:        (empty)",
            f"  Initial:       ${self.initial_capital:,.2f}",
            f"  Final:         ${self.final_equity:,.2f}",
            f"  Total return:  {self.total_return:+.2%}",
            f"  CAGR:          {self.cagr:+.2%}",
            f"  Sharpe:        {self.sharpe:.2f}",
            f"  Sortino:       {self.sortino:.2f}",
            f"  Max drawdown:  -{self.max_drawdown:.2%}",
            f"  Trades:        {len(self.closed_trades)} closed"
            + (f", {len(self.trades) - len(self.closed_trades)} open" if len(self.trades) != len(self.closed_trades) else ""),
            f"  Win rate:      {self.win_rate:.1%}",
            f"  Profit factor: {self.profit_factor:.2f}",
            f"  Exposure:      {self.exposure:.1%}",
        ]
        return "\n".join(lines)


@dataclass
class Backtester:
    """Runs a strategy over a series.

    - ``commission``: flat cost per order (entry and exit each pay it)
    - ``slippage_bps``: adverse fill adjustment in basis points of price
    - ``position_fraction``: fraction of current equity deployed per entry
    """

    initial_capital: float = 100_000.0
    commission: float = 1.0
    slippage_bps: float = 5.0
    position_fraction: float = 0.95

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not 0 < self.position_fraction <= 1:
            raise ValueError("position_fraction must be in (0, 1]")
        if self.commission < 0 or self.slippage_bps < 0:
            raise ValueError("commission and slippage must be non-negative")

    def run(self, strategy: Strategy, series: OHLCV) -> BacktestResult:
        if len(series) < 2:
            raise ValueError(f"need at least 2 bars, got {len(series)}")
        signals = strategy.signals(series)
        if len(signals) != len(series):
            raise ValueError(
                f"strategy returned {len(signals)} signals for {len(series)} bars"
            )

        cash = self.initial_capital
        shares = 0
        trades: list[Trade] = []
        equity_curve: list[float] = []
        slip = self.slippage_bps / 10_000.0

        for i, bar in enumerate(series):
            # Execute yesterday's signal at today's open.
            if i > 0:
                desired = signals[i - 1]
                if desired is Signal.LONG and shares == 0:
                    fill = bar.open * (1 + slip)
                    budget = cash * self.position_fraction - self.commission
                    qty = int(budget / fill)
                    if qty > 0:
                        shares = qty
                        cash -= qty * fill + self.commission
                        trades.append(Trade(series.symbol, bar.date, fill, qty))
                elif desired is Signal.FLAT and shares > 0:
                    fill = bar.open * (1 - slip)
                    cash += shares * fill - self.commission
                    trades[-1].exit_date = bar.date
                    trades[-1].exit_price = fill
                    shares = 0
            equity_curve.append(cash + shares * bar.close)

        return BacktestResult(
            symbol=series.symbol,
            strategy=strategy.name,
            initial_capital=self.initial_capital,
            equity_curve=equity_curve,
            dates=series.dates,
            trades=trades,
        )


def buy_and_hold(series: OHLCV, initial_capital: float = 100_000.0) -> BacktestResult:
    """Benchmark: buy at the first open, hold to the end."""

    class _Hold(Strategy):
        name = "buy_and_hold"

        def signals(self, s: OHLCV) -> list[Signal]:
            return [Signal.LONG] * len(s)

    return Backtester(initial_capital=initial_capital, commission=0.0, slippage_bps=0.0).run(
        _Hold(), series
    )
