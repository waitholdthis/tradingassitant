# ============================================================
# MARKET SCANNER
# Fetches OHLCV data, runs indicators, generates signals
# ============================================================

import time
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf
import pandas as pd

import indicators
import signals as sig_engine
from config import (
    LOOKBACK_PERIOD, INTRADAY_INTERVAL,
    PENNY_STOCK_MAX_PRICE, FOCUS_PENNY_STOCKS,
    MIN_SIGNAL_SCORE, ALERT_COOLDOWN_MINUTES,
    UNIVERSE_SCAN_WORKERS,
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


FETCH_RETRIES = 2          # extra attempts after the first failure
FETCH_BACKOFF_SECONDS = 2  # doubled on each retry


def fetch_data(ticker: str) -> pd.DataFrame | None:
    """Download OHLCV data with retries. Returns None on failure."""
    for attempt in range(FETCH_RETRIES + 1):
        try:
            df = yf.download(
                ticker,
                period=LOOKBACK_PERIOD,
                interval=INTRADAY_INTERVAL,
                progress=False,
                auto_adjust=True,
            )
            if df is None or df.empty or len(df) < 30:
                return None  # ticker has no usable data; retrying won't help
            # Flatten MultiIndex columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as e:
            if attempt < FETCH_RETRIES:
                time.sleep(FETCH_BACKOFF_SECONDS * 2 ** attempt)
            else:
                print(f"  ⚠ Data error for {ticker} after {attempt + 1} attempts: {e}")
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


# ── UNIVERSE SCAN ─────────────────────────────────────────────

def scan_universe(top_n: int = 10) -> list[dict]:
    """Scan every US-listed ticker and return the top N BUY signals.

    Uses a thread pool for parallel fetching. Expect 5–10 minutes for
    the full ~8,000-ticker universe.
    """
    from universe import get_universe

    tickers = get_universe()
    total   = len(tickers)
    done    = 0
    lock    = threading.Lock()
    buys: list[dict] = []

    print(f"\n  Universe scan: {total:,} tickers | {UNIVERSE_SCAN_WORKERS} workers")
    print("  This takes 5–10 minutes — progress below.\n")

    def _worker(ticker: str):
        nonlocal done
        result = scan_ticker(ticker)
        with lock:
            done += 1
            if done % 250 == 0 or done == total:
                pct = done * 100 // total
                bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                print(f"  [{bar}] {pct:3d}%  {done:,}/{total:,}", end="\r", flush=True)
            if result and result["signal"] == "BUY" and _meets_threshold(result):
                buys.append(result)

    with ThreadPoolExecutor(max_workers=UNIVERSE_SCAN_WORKERS) as pool:
        futures = {pool.submit(_worker, t): t for t in tickers}
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass  # individual ticker errors never abort the scan

    print(f"\n\n  Scan complete. {len(buys):,} BUY signals found across {total:,} tickers.")
    buys.sort(key=lambda r: r["score"], reverse=True)
    return buys[:top_n]
