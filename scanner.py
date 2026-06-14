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
    MIN_PRICE, MIN_AVG_DAILY_DOLLAR_VOL, MIN_AVG_DAILY_VOLUME,
    MAX_SPREAD_PROXY_PCT, ENFORCE_LIQUIDITY,
)


# ── LIQUIDITY GUARD ──────────────────────────────────────────

_INTERVAL_MINUTES = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30,
                     "60m": 60, "1h": 60, "1d": 390}


def _bars_per_day(interval: str = INTRADAY_INTERVAL) -> float:
    """Approximate regular-session bars per trading day for the interval."""
    mins = _INTERVAL_MINUTES.get(interval, 5)
    return max(1.0, 390.0 / mins)   # 6.5h regular session = 390 minutes


def liquidity_metrics(ind: dict) -> dict:
    """Derive tradability metrics from an indicator readout."""
    price = ind.get("price", 0.0)
    avg_bar_vol = ind.get("volume_avg", 0.0)
    bpd = _bars_per_day()
    avg_daily_vol = avg_bar_vol * bpd
    avg_daily_dollar_vol = avg_daily_vol * price
    bar_range = ind.get("price_high", price) - ind.get("price_low", price)
    spread_proxy_pct = (bar_range / price * 100) if price > 0 else 100.0
    return {
        "avg_daily_volume": int(avg_daily_vol),
        "avg_daily_dollar_vol": round(avg_daily_dollar_vol, 0),
        "spread_proxy_pct": round(spread_proxy_pct, 2),
    }


def liquidity_check(ind: dict) -> tuple[bool, str]:
    """Return (is_tradable, reason). Blocks illiquid pump-and-dump traps.

    Order matters: price floor first (junk shells), then dollar-volume (the
    real exit-liquidity test), then share volume, then the spread proxy.
    """
    if not ENFORCE_LIQUIDITY:
        return True, "liquidity guard off"
    price = ind.get("price", 0.0)
    m = liquidity_metrics(ind)
    if price < MIN_PRICE:
        return False, f"price ${price:.4g} < ${MIN_PRICE:.2f} floor"
    if m["avg_daily_dollar_vol"] < MIN_AVG_DAILY_DOLLAR_VOL:
        return False, (f"thin: ${m['avg_daily_dollar_vol']/1e6:.2f}M/day < "
                       f"${MIN_AVG_DAILY_DOLLAR_VOL/1e6:.2f}M (liquidity trap risk)")
    if m["avg_daily_volume"] < MIN_AVG_DAILY_VOLUME:
        return False, (f"low volume: {m['avg_daily_volume']:,} sh/day < "
                       f"{MIN_AVG_DAILY_VOLUME:,}")
    if m["spread_proxy_pct"] > MAX_SPREAD_PROXY_PCT:
        return False, (f"wide bars: {m['spread_proxy_pct']:.1f}% range > "
                       f"{MAX_SPREAD_PROXY_PCT:.0f}% (thin book / slippage)")
    return True, "liquid"


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
    tradable, why = liquidity_check(ind)
    result["liquidity"] = liquidity_metrics(ind)
    result["tradable"]  = tradable
    result["liquidity_note"] = why
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
    """Filter to BUY/SELL signals above threshold that also pass the liquidity
    guard (so we never alert on a name we couldn't actually exit)."""
    return [
        r for r in results
        if r["signal"] in ("BUY", "SELL")
        and _meets_threshold(r)
        and r.get("tradable", True)
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
            if (result and result["signal"] == "BUY" and _meets_threshold(result)
                    and result.get("tradable", True)):
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


def screen_penny_movers(top_n: int = 10, max_price: float = None) -> list[dict]:
    """Scan the universe for liquid penny stocks showing real momentum.

    Unlike a naive penny scanner, this REQUIRES the liquidity guard to pass
    (genuine dollar-volume) and ranks by a blend of signal score and relative
    volume — so it surfaces movers you can actually trade, not illiquid pumps.
    """
    from universe import get_universe
    max_price = max_price if max_price is not None else PENNY_STOCK_MAX_PRICE
    tickers = get_universe()
    total   = len(tickers)
    done    = 0
    lock    = threading.Lock()
    movers: list[dict] = []

    print(f"\n  Penny-mover screen: {total:,} tickers | filter ≤${max_price:.2f}, "
          f"liquid only")

    def _worker(ticker: str):
        nonlocal done
        result = scan_ticker(ticker)
        with lock:
            done += 1
            if done % 250 == 0 or done == total:
                pct = done * 100 // total
                bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                print(f"  [{bar}] {pct:3d}%  {done:,}/{total:,}", end="\r", flush=True)
            if not result or not result.get("tradable"):
                return
            ind = result["indicators"]
            if ind["price"] > max_price:
                return
            if result["signal"] != "BUY" or not _meets_threshold(result):
                return
            movers.append(result)

    with ThreadPoolExecutor(max_workers=UNIVERSE_SCAN_WORKERS) as pool:
        futures = {pool.submit(_worker, t): t for t in tickers}
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass

    # Rank by score, then relative volume (momentum confirmation).
    movers.sort(key=lambda r: (r["score"], r["indicators"]["volume_ratio"]),
                reverse=True)
    print(f"\n\n  {len(movers):,} liquid penny BUY signals found.")
    return movers[:top_n]
