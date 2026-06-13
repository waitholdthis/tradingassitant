# Trading Assistant

A self-contained Python toolkit for technical analysis, strategy backtesting,
and risk management. The core has **zero dependencies** — everything runs on
the standard library — with optional live data via `yfinance`.

> **Disclaimer:** this is an analysis and research tool, not financial advice.
> Backtested performance does not guarantee future results.

## Features

- **Indicators** — SMA, EMA, WMA, RSI (Wilder), MACD, Bollinger Bands, ATR,
  Stochastic, OBV, VWAP, ROC, rolling channels
- **Strategies** — SMA crossover, RSI mean reversion, MACD momentum, Bollinger
  breakout, Donchian channel breakout, and a majority-vote **ensemble**
- **Backtester** — event-driven, fills at next bar's open (no look-ahead),
  commission + slippage modeling, full metrics: CAGR, Sharpe, Sortino, max
  drawdown, win rate, profit factor, market exposure
- **Risk management** — fixed-fractional and ATR-based position sizing, capped
  Kelly criterion, stop-loss/take-profit brackets, trailing stops
- **Portfolio tracking** — positions, average cost, realized/unrealized P&L,
  allocation weights, JSON persistence
- **Alerts** — watchlist rules: price levels, RSI thresholds, SMA crosses,
  volume spikes
- **Data** — CSV loading (Yahoo-style headers), reproducible synthetic data
  for testing, optional Yahoo Finance fetching

## Install

```bash
pip install -e .            # core (no dependencies)
pip install -e ".[live]"    # + yfinance for live data
pip install -e ".[dev]"     # + pytest
```

## CLI

```bash
# Technical snapshot: trend, momentum, volatility, 52-week range
trading-assistant analyze --csv data/AAPL.csv
trading-assistant analyze --fetch AAPL --period 1y   # needs yfinance + network
trading-assistant analyze --demo                     # synthetic data

# Backtest a strategy against buy-and-hold
trading-assistant backtest --csv data/AAPL.csv --strategy sma
trading-assistant backtest --demo --strategy ensemble --capital 50000

# Run every built-in strategy on the same data, ranked by Sharpe
trading-assistant compare --demo

# Position sizing with stop/target levels
trading-assistant size --equity 50000 --price 185.50 --atr 3.2
trading-assistant size --equity 50000 --price 185.50 --stop-pct 0.05 --risk 0.02
```

(Or `python -m trading_assistant ...` without installing.)

## Library

```python
from trading_assistant import Backtester, SmaCrossover, load_csv

series = load_csv("data/AAPL.csv")
result = Backtester(initial_capital=100_000).run(SmaCrossover(20, 50), series)
print(result.summary())
print(f"Sharpe: {result.sharpe:.2f}, max drawdown: {result.max_drawdown:.1%}")
```

Build your own strategy by subclassing `Strategy`:

```python
from trading_assistant.strategies import Strategy, Signal
from trading_assistant import indicators as ind

class GoldenCross(Strategy):
    name = "golden_cross"

    def signals(self, series):
        fast, slow = ind.sma(series.closes, 50), ind.sma(series.closes, 200)
        return [
            Signal.NONE if s is None
            else Signal.LONG if f > s
            else Signal.FLAT
            for f, s in zip(fast, slow)
        ]
```

Risk sizing and alerts:

```python
from trading_assistant.risk import atr_position_size, atr_bracket
from trading_assistant.alerts import Watchlist, RsiThreshold, SmaCross

shares = atr_position_size(equity=50_000, price=185.5, atr_value=3.2)
levels = atr_bracket(entry=185.5, atr_value=3.2)

wl = Watchlist()
wl.add("AAPL", RsiThreshold(threshold=30, below=True))
wl.add("AAPL", SmaCross(20, 50))
for alert in wl.evaluate({"AAPL": series}):
    print(alert.message)
```

## Design notes

- **No look-ahead bias:** strategies only see data up to the current bar, and
  the backtester executes each signal at the *next* bar's open. A test asserts
  signals on a data prefix match signals on the full series.
- **Warm-up handling:** indicators return `None` until they have enough data;
  strategies emit `Signal.NONE` during warm-up rather than guessing.
- **Realistic costs:** every fill pays commission and adverse slippage, so
  high-churn strategies are penalized appropriately.

## Tests

```bash
python -m pytest
```
