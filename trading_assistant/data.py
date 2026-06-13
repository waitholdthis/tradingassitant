"""Market data: OHLCV containers, CSV loading, synthetic series, live quotes."""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterator, Sequence


@dataclass
class Bar:
    """A single OHLCV bar."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(f"{self.date}: low {self.low} > high {self.high}")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"{self.date}: open {self.open} outside [{self.low}, {self.high}]")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"{self.date}: close {self.close} outside [{self.low}, {self.high}]")


@dataclass
class OHLCV:
    """A time-ordered series of OHLCV bars for one symbol."""

    symbol: str
    bars: list[Bar] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.bars)

    def __iter__(self) -> Iterator[Bar]:
        return iter(self.bars)

    def __getitem__(self, i: int) -> Bar:
        return self.bars[i]

    @property
    def closes(self) -> list[float]:
        return [b.close for b in self.bars]

    @property
    def opens(self) -> list[float]:
        return [b.open for b in self.bars]

    @property
    def highs(self) -> list[float]:
        return [b.high for b in self.bars]

    @property
    def lows(self) -> list[float]:
        return [b.low for b in self.bars]

    @property
    def volumes(self) -> list[float]:
        return [b.volume for b in self.bars]

    @property
    def dates(self) -> list[date]:
        return [b.date for b in self.bars]

    def slice(self, start: date | None = None, end: date | None = None) -> "OHLCV":
        bars = [
            b
            for b in self.bars
            if (start is None or b.date >= start) and (end is None or b.date <= end)
        ]
        return OHLCV(self.symbol, bars)

    def validate(self) -> None:
        """Raise if bars are out of order or duplicated."""
        for prev, cur in zip(self.bars, self.bars[1:]):
            if cur.date <= prev.date:
                raise ValueError(
                    f"{self.symbol}: bars not strictly increasing at {prev.date} -> {cur.date}"
                )


def load_csv(path: str, symbol: str | None = None) -> OHLCV:
    """Load an OHLCV series from a CSV file.

    Accepts standard headers (case-insensitive): Date, Open, High, Low, Close,
    Volume. ``Adj Close`` is used in place of Close when present.
    """
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: empty CSV")
        cols = {name.strip().lower(): name for name in reader.fieldnames}
        close_col = cols.get("adj close", cols.get("close"))
        required = ["date", "open", "high", "low"]
        missing = [c for c in required if c not in cols] + ([] if close_col else ["close"])
        if missing:
            raise ValueError(f"{path}: missing columns {missing}")

        bars = []
        for row in reader:
            raw_date = row[cols["date"]].strip()
            try:
                d = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
            except ValueError:
                d = datetime.strptime(raw_date, "%m/%d/%Y").date()
            bars.append(
                Bar(
                    date=d,
                    open=float(row[cols["open"]]),
                    high=float(row[cols["high"]]),
                    low=float(row[cols["low"]]),
                    close=float(row[close_col]),
                    volume=float(row[cols["volume"]]) if "volume" in cols and row[cols["volume"]] else 0.0,
                )
            )
    bars.sort(key=lambda b: b.date)
    name = symbol or path.rsplit("/", 1)[-1].rsplit(".", 1)[0].upper()
    series = OHLCV(name, bars)
    series.validate()
    return series


def synthetic_series(
    symbol: str = "TEST",
    days: int = 500,
    start_price: float = 100.0,
    drift: float = 0.0003,
    volatility: float = 0.015,
    seed: int | None = 42,
    start: date | None = None,
) -> OHLCV:
    """Generate a geometric-Brownian-motion price series for testing and demos."""
    rng = random.Random(seed)
    d = start or (date.today() - timedelta(days=int(days * 1.5)))
    price = start_price
    bars: list[Bar] = []
    while len(bars) < days:
        if d.weekday() < 5:  # trading days only
            ret = drift + volatility * rng.gauss(0, 1)
            close = price * math.exp(ret)
            o = price * math.exp(volatility * 0.3 * rng.gauss(0, 1))
            hi = max(o, close) * (1 + abs(rng.gauss(0, volatility * 0.5)))
            lo = min(o, close) * (1 - abs(rng.gauss(0, volatility * 0.5)))
            vol = max(0.0, rng.gauss(1_000_000, 250_000))
            bars.append(Bar(d, round(o, 4), round(hi, 4), round(lo, 4), round(close, 4), round(vol)))
            price = close
        d += timedelta(days=1)
    return OHLCV(symbol, bars)


def fetch_yfinance(symbol: str, period: str = "1y", interval: str = "1d") -> OHLCV:
    """Fetch historical bars from Yahoo Finance (requires the ``yfinance`` package
    and network access)."""
    try:
        import yfinance  # type: ignore
    except ImportError as e:
        raise RuntimeError("install yfinance to fetch live data: pip install yfinance") from e

    df = yfinance.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        raise ValueError(f"no data returned for {symbol!r}")
    bars = [
        Bar(
            date=idx.date() if hasattr(idx, "date") else idx,
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=float(row.get("Volume", 0.0) or 0.0),
        )
        for idx, row in df.iterrows()
    ]
    return OHLCV(symbol.upper(), bars)


def returns(closes: Sequence[float]) -> list[float]:
    """Simple period-over-period returns."""
    return [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
