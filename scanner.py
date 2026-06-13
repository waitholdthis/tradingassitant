# ============================================================
# MARKET SCANNER
# Fetches OHLCV data, runs indicators, generates signals
# ============================================================

import time
import datetime
import yfinance as yf
import pandas as pd

import indicators
import signals as sig_engine
from config import (
    LOOKBACK_PERIOD, INTRADAY_INTERVAL,
    PENNY_STOCK_MAX_PRICE, FOCUS_PENNY_STOCKS,
    MIN_SIGNAL_SCORE, ALERT_COOLDOWN_MINUTES,
)


# ── COOLDOWN TRACKER ─────────────────────────────────────────
_last_alerted: dict[str, datetime.datetime] = {}


def _in_cooldown(ticker: str, signal: str) -> bool:
    key = f"{ticker}:{signal}"
    if key not in _last_alerted:
        return False
    elapsed = (datetime.datetime.now() - _last_alerted[key]).total_seconds() / 60
    return elapsed < ALERT_COOLDOWN_MINUTES


def _mark_alerted(ticker: str, signal: str):
    _last_alerted[f"{ticker}:{signal}"] = datetime.datetime.now()


def fetch_data(ticker: str) -> pd.DataFrame | None:
    """Download OHLCV data. Returns None on failure."""
    try:
        df = yf.download(
            ticker,
            period=LOOKBACK_PERIOD,
            interval=INTRADAY_INTERVAL,
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty or len(df) < 30:
            return None
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        print(f"  ⚠ Data error for {ticker}: {e}")
        return None


def scan_ticker(ticker: str) -> dict | None:
    """
    Full pipeline: fetch → indicators → signal.
    Returns result dict or None if data unavailable.
    """
    df = fetch_data(ticker)
    if df is None:
        return None

    ind = indicators.run_all(df)
    price    = ind["price"]
    is_penny = price <= PENNY_STOCK_MAX_PRICE

    result = sig_engine.generate_signal(ind, ticker, is_penny=is_penny)
    return result


def scan_all(watchlist: list[str], show_all: bool = True) -> list[dict]:
    """
    Scan every ticker in the watchlist.
    Returns list of results, filtered and sorted by score.
    """
    results = []
    for ticker in watchlist:
        result = scan_ticker(ticker)
        if result is None:
            continue

        # Penny stock focus filter
        if FOCUS_PENNY_STOCKS and not result["is_penny"]:
            continue

        results.append(result)
        time.sleep(0.15)   # polite delay between API calls

    # Sort: BUY (high score) first, SELL (low score) last
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def get_actionable(results: list[dict]) -> list[dict]:
    """Filter to only BUY/SELL signals above minimum score."""
    return [
        r for r in results
        if r["signal"] in ("BUY", "SELL")
        and _meets_threshold(r)
        and not _in_cooldown(r["ticker"], r["signal"])
    ]


def _meets_threshold(result: dict) -> bool:
    score = result["score"]
    signal = result["signal"]
    if signal == "BUY"  and score >= MIN_SIGNAL_SCORE:
        return True
    if signal == "SELL" and score <= (100 - MIN_SIGNAL_SCORE):
        return True
    return False


def mark_alerts_sent(actionable: list[dict]):
    for r in actionable:
        _mark_alerted(r["ticker"], r["signal"])
