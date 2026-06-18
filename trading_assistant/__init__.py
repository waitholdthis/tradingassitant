"""Trading Assistant — analysis, signals, backtesting, and risk management.

A self-contained trading toolkit:

- ``data``        OHLCV containers, CSV loading, synthetic data, optional live quotes
- ``indicators``  SMA, EMA, RSI, MACD, Bollinger Bands, ATR, Stochastic, OBV, VWAP
- ``strategies``  Signal-generating strategies and a composite ensemble
- ``backtest``    Event-driven backtester with realistic costs and full metrics
- ``risk``        Position sizing (fixed-fractional, ATR, Kelly) and stop management
- ``portfolio``   Position tracking and P&L
- ``alerts``      Watchlist alert rules
"""

__version__ = "1.0.0"

from .data import OHLCV, load_csv, synthetic_series
from .backtest import Backtester, BacktestResult
from .strategies import (
    SmaCrossover,
    RsiMeanReversion,
    MacdMomentum,
    BollingerBreakout,
    EnsembleStrategy,
)

__all__ = [
    "OHLCV",
    "load_csv",
    "synthetic_series",
    "Backtester",
    "BacktestResult",
    "SmaCrossover",
    "RsiMeanReversion",
    "MacdMomentum",
    "BollingerBreakout",
    "EnsembleStrategy",
]
