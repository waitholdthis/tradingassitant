# ============================================================
# CONFIDENCE CALIBRATION
#
# Turns the signal engine's 0-100 score into a *measured*
# probability of success — the only honest way to say
# "80% confidence."
#
# Method (walk-forward, no look-ahead):
#   1. For each symbol, fetch historical OHLCV.
#   2. At each bar t, run the REAL signal engine on bars[0..t].
#   3. For every actionable BUY/SELL, simulate its trade plan:
#      enter at the open of bar t+1, then check whether price
#      reaches the take-profit (TP1) before the stop within a
#      holding window.
#   4. Bucket outcomes by score and compute the win rate with a
#      Wilson lower bound (so small samples can't claim 80%).
#
# The result (calibration.json) maps score -> confidence %.
# A signal is only labelled "80% confidence" if its score bucket
# HISTORICALLY hit its target 80%+ of the time, with enough
# samples to trust the number. If the data doesn't support it,
# the system says so instead of inventing it.
#
# Usage:
#   python calibration.py                 # calibrate on default basket
#   python calibration.py --interval 1d --period 3y
#   python calibration.py --symbols AAPL,TSLA,SNDL --stride 2
# ============================================================

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys

import pandas as pd
import yfinance as yf

import indicators
import signals as sig_engine

CALIBRATION_FILE = "calibration.json"

# A basket spanning regimes: large-cap trenders, high-beta movers,
# index anchors, and a few low-priced/penny names. Calibrating across
# many symbols gives the score->winrate map far more samples than any
# single ticker could.
DEFAULT_BASKET = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMZN", "GOOGL",
    "SPY", "QQQ", "JPM", "XOM", "BAC", "F", "PLTR", "SOFI",
    "MARA", "RIOT", "SNDL", "NIO",
]

# Walk-forward parameters (overridable from the CLI).
WINDOW       = 250    # bars of history fed to the engine at each step
MAX_HOLD     = 10     # bars to wait for target/stop after entry
MIN_BARS     = 60     # skip symbols/leading bars with too little history
STRIDE       = 1      # evaluate every Nth bar (raise to speed up)
MIN_SAMPLES  = 30     # a bucket needs this many trades to report a number
WILSON_Z     = 1.2816 # 80% one-sided CI (conservative lower bound)

# Score buckets. BUY signals live in 65-100, SELL in 0-35.
BUY_EDGES  = [65, 70, 75, 80, 85, 90, 101]
SELL_EDGES = [0, 10, 15, 20, 25, 30, 36]


# ── STATS ─────────────────────────────────────────────────────

def wilson_lower_bound(wins: int, n: int, z: float = WILSON_Z) -> float:
    """Lower bound of a binomial proportion's confidence interval.

    Penalizes small samples: 8/10 wins reports far below 80% because we
    can't yet trust it. This is what keeps the confidence number honest.
    """
    if n == 0:
        return 0.0
    phat = wins / n
    denom = 1 + z * z / n
    center = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return max(0.0, (center - margin) / denom)


def _bucket_label(score: int, edges: list[int]) -> int | None:
    for i in range(len(edges) - 1):
        if edges[i] <= score < edges[i + 1]:
            return edges[i]
    return None


# ── DATA ──────────────────────────────────────────────────────

def fetch_history(symbol: str, period: str, interval: str) -> pd.DataFrame | None:
    """Download OHLCV history for calibration. Returns None on failure."""
    try:
        df = yf.download(symbol, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < MIN_BARS:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        print(f"  ! {symbol}: fetch failed ({e})")
        return None


# ── OUTCOME SIMULATION ────────────────────────────────────────

def _simulate(df: pd.DataFrame, entry_idx: int, plan: dict, signal: str,
              max_hold: int, target_rr: float | None = None) -> bool | None:
    """Did the trade hit its target before its stop, entering at entry_idx's open?

    Returns True (win), False (loss), or None (not enough forward bars).
    ``target_rr`` overrides the take-profit distance (in multiples of the
    stop distance R); None uses the plan's TP1. A smaller target_rr is easier
    to reach, so the measured win rate rises as target_rr falls — this is the
    knob that produces an 80%-confidence target.
    Conservative tie-break: if a single bar spans both stop and target,
    count it as a loss — understates the win rate rather than inflating it.
    """
    entry = float(df["Open"].iloc[entry_idx])
    if entry <= 0:
        return None
    stop = plan["stop"]
    if target_rr is None:
        tp1 = plan["tp1"]
    else:
        direction = 1 if signal == "BUY" else -1
        tp1 = entry + direction * plan["risk_per_share"] * target_rr
    end = min(entry_idx + max_hold, len(df) - 1)
    if end <= entry_idx:
        return None

    for j in range(entry_idx, end + 1):
        hi = float(df["High"].iloc[j])
        lo = float(df["Low"].iloc[j])
        if signal == "BUY":
            if lo <= stop:          # stop checked first (conservative)
                return False
            if hi >= tp1:
                return True
        else:  # SELL / short
            if hi >= stop:
                return False
            if lo <= tp1:
                return True

    # Neither level hit within the window — resolve by final close.
    exit_close = float(df["Close"].iloc[end])
    return (exit_close > entry) if signal == "BUY" else (exit_close < entry)


# ── WALK-FORWARD OVER ONE SYMBOL ──────────────────────────────

def _walk_symbol(symbol: str, df: pd.DataFrame, window: int, stride: int,
                 max_hold: int, tally: dict, target_rr: float | None = None) -> int:
    """Accumulate (score-bucket -> wins/losses) outcomes for one symbol."""
    n = len(df)
    evaluated = 0
    # Need room for a window behind and an entry+hold ahead.
    for t in range(window, n - max_hold - 1, stride):
        win_df = df.iloc[t - window:t + 1]
        try:
            ind = indicators.run_all(win_df)
        except Exception:
            continue
        price = ind["price"]
        is_penny = price <= 5.0
        result = sig_engine.generate_signal(ind, symbol, is_penny=is_penny)
        signal = result["signal"]
        if signal not in ("BUY", "SELL"):
            continue
        plan = result.get("trade_plan")
        if not plan:
            continue

        edges = BUY_EDGES if signal == "BUY" else SELL_EDGES
        bucket = _bucket_label(result["score"], edges)
        if bucket is None:
            continue

        outcome = _simulate(df, t + 1, plan, signal, max_hold, target_rr)
        if outcome is None:
            continue

        side = tally[signal.lower()]
        cell = side.setdefault(bucket, {"wins": 0, "n": 0})
        cell["n"] += 1
        cell["wins"] += 1 if outcome else 0
        evaluated += 1
    return evaluated


# ── DRIVER ────────────────────────────────────────────────────

def calibrate(symbols: list[str], period: str = "2y", interval: str = "1d",
              window: int = WINDOW, stride: int = STRIDE,
              max_hold: int = MAX_HOLD, target_rr: float | None = None) -> dict:
    """Run walk-forward calibration across symbols and return the report.

    ``target_rr`` (in multiples of the stop distance) overrides the take-profit
    used to label wins. Lower values measure a closer, higher-probability
    target — the knob for reaching an 80%-confidence level.
    """
    tally: dict = {"buy": {}, "sell": {}}
    tgt = f"{target_rr:g}R" if target_rr is not None else "plan TP1 (2R)"
    print(f"\n  Calibrating on {len(symbols)} symbols "
          f"({interval} bars, {period}, window={window}, hold={max_hold}, target={tgt})")
    print(f"  {'─'*54}")

    total_trades = 0
    for i, sym in enumerate(symbols, 1):
        df = fetch_history(sym, period, interval)
        if df is None:
            print(f"  [{i:>2}/{len(symbols)}] {sym:<6} skipped (no data)")
            continue
        evald = _walk_symbol(sym, df, window, stride, max_hold, tally, target_rr)
        total_trades += evald
        print(f"  [{i:>2}/{len(symbols)}] {sym:<6} {len(df):>4} bars  "
              f"{evald:>4} sim-trades")

    report = _finalize(tally, total_trades, symbols, period, interval,
                       window, stride, max_hold, target_rr)
    return report


def _finalize(tally, total_trades, symbols, period, interval, window,
              stride, max_hold, target_rr=None) -> dict:
    eff_rr = target_rr if target_rr is not None else sig_engine.TP1_RR

    def _bucketize(side: dict) -> dict:
        out = {}
        for bucket, cell in sorted(side.items()):
            n, wins = cell["n"], cell["wins"]
            rate = wins / n if n else 0.0
            wlb = wilson_lower_bound(wins, n)
            # Per-trade expectancy in R: win pays +eff_rr, loss pays -1R (the stop).
            # This is the number that actually decides profitability — a high
            # win rate at a tiny target can still be a losing system.
            expectancy = rate * eff_rr - (1 - rate)
            out[str(bucket)] = {
                "n": n,
                "wins": wins,
                "win_rate": round(rate, 4),
                "confidence": round(wlb, 4),   # Wilson lower bound = reported %
                "expectancy_r": round(expectancy, 4),
                "trusted": n >= MIN_SAMPLES,
            }
        return out

    return {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "params": {
            "symbols": symbols, "period": period, "interval": interval,
            "window": window, "stride": stride, "max_hold": max_hold,
            "min_samples": MIN_SAMPLES, "wilson_z": WILSON_Z,
            "stop_atr_mult": sig_engine.STOP_ATR_MULT,
            "target_rr": target_rr if target_rr is not None else sig_engine.TP1_RR,
        },
        "total_trades": total_trades,
        "buy": _bucketize(tally["buy"]),
        "sell": _bucketize(tally["sell"]),
    }


def save(report: dict, path: str = CALIBRATION_FILE) -> None:
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Saved calibration -> {path}")


# ── LOOKUP (used by the live signal engine) ───────────────────

_cache: dict | None = None


def load(path: str = CALIBRATION_FILE) -> dict | None:
    """Load the calibration table once, cached. Returns None if absent."""
    global _cache
    if _cache is not None:
        return _cache
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            _cache = json.load(f)
    except Exception:
        return None
    return _cache


def confidence_for(score: int, signal: str, path: str = CALIBRATION_FILE):
    """Return (confidence_pct, trusted) for a score, or (None, False).

    confidence_pct is the historical Wilson-lower-bound win rate for the
    score's bucket. ``trusted`` is False when the bucket had too few samples
    to rely on — callers should treat those as uncalibrated.
    """
    table = load(path)
    if not table:
        return None, False
    side = table.get(signal.lower())
    if not side:
        return None, False
    edges = BUY_EDGES if signal == "BUY" else SELL_EDGES
    bucket = _bucket_label(int(score), edges)
    if bucket is None:
        return None, False
    cell = side.get(str(bucket))
    if not cell:
        return None, False
    return round(cell["confidence"] * 100, 1), cell["trusted"]


def print_report(report: dict) -> None:
    print(f"\n  {'═'*54}")
    print(f"  CALIBRATION REPORT  ({report['total_trades']:,} simulated trades)")
    print(f"  {'═'*54}")
    for side in ("buy", "sell"):
        rows = report[side]
        if not rows:
            continue
        print(f"\n  {side.upper()} signals:")
        print(f"    {'score':>7}  {'trades':>7}  {'raw win%':>9}  {'confidence':>11}  {'exp(R)':>8}  trusted")
        for bucket, cell in rows.items():
            star = "✓" if cell["trusted"] else "·"
            print(f"    {bucket+'+':>7}  {cell['n']:>7}  "
                  f"{cell['win_rate']*100:>8.1f}%  {cell['confidence']*100:>10.1f}%  "
                  f"{cell['expectancy_r']:>+8.3f}  {star:>7}")
    print(f"\n  ✓ = enough samples to trust (n >= {MIN_SAMPLES})")
    print("  'confidence' = Wilson lower-bound hit rate (earns 80% only if measured).")
    print("  'exp(R)' = expectancy per trade in R (stop = 1R). THIS decides profit:")
    print("  a high win rate at a tiny target can still lose money. Maximize exp(R).\n")


def main():
    p = argparse.ArgumentParser(description="Calibrate signal confidence")
    p.add_argument("--symbols", type=str, default="",
                   help="comma-separated tickers (default: built-in basket)")
    p.add_argument("--period", type=str, default="2y")
    p.add_argument("--interval", type=str, default="1d")
    p.add_argument("--window", type=int, default=WINDOW)
    p.add_argument("--stride", type=int, default=STRIDE)
    p.add_argument("--max-hold", type=int, default=MAX_HOLD)
    p.add_argument("--target-rr", type=float, default=None,
                   help="take-profit distance in R (default: plan TP1 = 2R). "
                        "Lower = closer target = higher win rate.")
    args = p.parse_args()

    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               or DEFAULT_BASKET)
    report = calibrate(symbols, period=args.period, interval=args.interval,
                       window=args.window, stride=args.stride,
                       max_hold=args.max_hold, target_rr=args.target_rr)
    print_report(report)
    save(report)


if __name__ == "__main__":
    main()
