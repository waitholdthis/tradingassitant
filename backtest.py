#!/usr/bin/env python3
# ============================================================
# INDICATOR & SIGNAL BACKTEST
# Tests all indicators across 5 synthetic market scenarios:
#   1. STRONG UPTREND   — expects BUY
#   2. STRONG DOWNTREND — expects SELL
#   3. SIDEWAYS/RANGING — expects HOLD
#   4. OVERSOLD BOUNCE  — expects BUY (RSI recovery)
#   5. PENNY SPIKE      — expects BUY with volume confirmation
# ============================================================

import sys
import math
import numpy as np
import pandas as pd
from colorama import Fore, Style, init

init(autoreset=True)
sys.path.insert(0, ".")
import indicators
import signals as sig_engine

PASS = Fore.GREEN  + Style.BRIGHT + "  PASS" + Style.RESET_ALL
FAIL = Fore.RED    + Style.BRIGHT + "  FAIL" + Style.RESET_ALL
WARN = Fore.YELLOW + Style.BRIGHT + "  WARN" + Style.RESET_ALL

# ── DATA GENERATORS ──────────────────────────────────────────

def make_uptrend(n=120, seed=1) -> pd.DataFrame:
    """Steadily rising prices with moderate volume."""
    np.random.seed(seed)
    trend = np.linspace(10, 18, n)
    noise = np.random.randn(n) * 0.08
    close = pd.Series(trend + noise)
    high  = close + abs(np.random.randn(n) * 0.05)
    low   = close - abs(np.random.randn(n) * 0.04)
    vol   = pd.Series(np.random.randint(100_000, 200_000, n).astype(float))
    return pd.DataFrame({"Open": close - 0.02, "High": high, "Low": low, "Close": close, "Volume": vol})


def make_downtrend(n=120, seed=2) -> pd.DataFrame:
    """Steadily falling prices with increasing volume."""
    np.random.seed(seed)
    trend = np.linspace(20, 10, n)
    noise = np.random.randn(n) * 0.08
    close = pd.Series(trend + noise)
    high  = close + abs(np.random.randn(n) * 0.04)
    low   = close - abs(np.random.randn(n) * 0.06)
    vol   = pd.Series(np.linspace(100_000, 300_000, n) + np.random.randint(0, 50_000, n))
    return pd.DataFrame({"Open": close + 0.02, "High": high, "Low": low, "Close": close, "Volume": vol})


def make_sideways(n=120, seed=0) -> pd.DataFrame:
    """Mean-reverting choppy price — no directional trend."""
    np.random.seed(seed)
    p = [15.0]
    for _ in range(n - 1):
        p.append(p[-1] * 0.85 + 15 * 0.15 + np.random.randn() * 0.08)
    close = pd.Series(p)
    high  = close + abs(np.random.randn(n) * 0.04)
    low   = close - abs(np.random.randn(n) * 0.04)
    vol   = pd.Series(np.random.randint(80_000, 120_000, n).astype(float))
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": vol})


def make_oversold_bounce(n=120, seed=4) -> pd.DataFrame:
    """Crash then recovery: price bounces off bottom with volume surge.
    105 bars crash (20→8), 15 bars recovery (8→8.4, +5%).
    Volume spike on recovery bars flips Supertrend bullish = confirmed reversal.
    """
    np.random.seed(seed)
    crash    = np.linspace(20, 8, 105) + np.random.randn(105) * 0.1
    recovery = np.linspace(8.0, 8.4, 15) + np.random.randn(15) * 0.05
    close    = pd.Series(np.concatenate([crash, recovery]))
    high     = close + abs(np.random.randn(n) * 0.04)
    low      = close - abs(np.random.randn(n) * 0.06)
    vol_base = np.random.randint(100_000, 150_000, n).astype(float)
    vol_base[-10:] *= 4.0   # volume surge on recovery (current scan point)
    vol = pd.Series(vol_base)
    return pd.DataFrame({"Open": close + 0.05, "High": high, "Low": low, "Close": close, "Volume": vol})


def make_penny_spike(n=120, seed=5) -> pd.DataFrame:
    """Low-price stock with a volume spike + price surge at the end."""
    np.random.seed(seed)
    base = np.linspace(0.80, 1.10, n) + np.random.randn(n) * 0.02
    # Surge in last 10 bars
    base[-10:] += np.linspace(0, 0.40, 10)
    close = pd.Series(np.clip(base, 0.50, 5.00))
    high  = close + abs(np.random.randn(n) * 0.02)
    low   = close - abs(np.random.randn(n) * 0.01)
    vol_base = np.random.randint(50_000, 100_000, n).astype(float)
    vol_base[-10:] *= 5  # 5× volume spike
    vol = pd.Series(vol_base)
    return pd.DataFrame({"Open": close - 0.01, "High": high, "Low": low, "Close": close, "Volume": vol})


# ── ASSERTION HELPERS ─────────────────────────────────────────

checks_run  = 0
checks_pass = 0
checks_fail = 0

def check(label: str, condition: bool, actual=None, hint: str = ""):
    global checks_run, checks_pass, checks_fail
    checks_run += 1
    status = PASS if condition else FAIL
    if condition:
        checks_pass += 1
    else:
        checks_fail += 1
    extra = f"  (got {actual})" if actual is not None and not condition else ""
    hint_str = f"  [{hint}]" if hint and not condition else ""
    print(f"    {status}  {label}{extra}{hint_str}")


def section(title: str):
    print(f"\n  {'─'*56}")
    print(f"  {Fore.CYAN}{Style.BRIGHT}{title}{Style.RESET_ALL}")
    print(f"  {'─'*56}")


# ── SCENARIO RUNNER ───────────────────────────────────────────

def run_scenario(name: str, df: pd.DataFrame, expected_signal: str,
                 is_penny: bool = False, ticker: str = "TEST"):
    print(f"\n{'═'*60}")
    print(f"  📊  SCENARIO: {Style.BRIGHT}{name}{Style.RESET_ALL}")
    print(f"      Expected signal: {Fore.CYAN}{expected_signal}{Style.RESET_ALL}"
          f"{'  [PENNY]' if is_penny else ''}")
    print(f"{'═'*60}")

    ind = indicators.run_all(df)
    result = sig_engine.generate_signal(ind, ticker, is_penny=is_penny)

    # ── Indicator sanity checks ───────────────────────────────
    section("Indicator Range Checks")

    check("RSI in [0, 100]",
          0 <= ind["rsi"] <= 100, ind["rsi"])

    check("Stochastic %K in [0, 100]",
          0 <= ind["stoch_k"] <= 100, ind["stoch_k"])

    check("Stochastic %D in [0, 100]",
          0 <= ind["stoch_d"] <= 100, ind["stoch_d"])

    check("BB %B is a real number (no NaN)",
          not math.isnan(ind["bb_pct_b"]), ind["bb_pct_b"])

    check("BB upper > BB lower",
          ind["bb_upper"] > ind["bb_lower"],
          f"{ind['bb_upper']:.4f} vs {ind['bb_lower']:.4f}")

    check("BB mid between upper/lower",
          ind["bb_lower"] <= ind["bb_mid"] <= ind["bb_upper"])

    check("ATR > 0",
          ind["atr"] > 0, ind["atr"])

    check("Volume ratio > 0",
          ind["volume_ratio"] > 0, ind["volume_ratio"])

    check("Price matches last Close",
          abs(ind["price"] - float(df["Close"].iloc[-1])) < 0.001,
          ind["price"])

    check("EMA9 is a real number",
          not math.isnan(ind["ema_9"]))

    check("EMA21 is a real number",
          not math.isnan(ind["ema_21"]))

    # ── Indicator value prints ────────────────────────────────
    section("Indicator Readout")
    print(f"    Price     ${ind['price']:.4f}")
    print(f"    RSI       {ind['rsi']:.1f}  {'(oversold)' if ind['rsi'] < 30 else '(overbought)' if ind['rsi'] > 70 else ''}")
    print(f"    MACD      {ind['macd']:+.4f}  (hist {ind['macd_hist']:+.4f})")
    print(f"    BB%%B      {ind['bb_pct_b']:.3f}  (upper {ind['bb_upper']:.4f} / lower {ind['bb_lower']:.4f})")
    print(f"    EMA 9/21  {ind['ema_9']:.4f} / {ind['ema_21']:.4f}")
    print(f"    Stoch K/D {ind['stoch_k']:.1f} / {ind['stoch_d']:.1f}")
    print(f"    ATR       {ind['atr']:.4f}")
    print(f"    Volume    {ind['volume']:,}  ({ind['volume_ratio']:.1f}x avg)"
          f"{'  🔥 SPIKE' if ind['volume_spike'] else ''}")

    # ── Signal checks ─────────────────────────────────────────
    section("Signal Checks")

    check(f"Signal generated (not None)",
          result is not None)

    check(f"Signal is valid enum",
          result["signal"] in ("BUY", "SELL", "HOLD"),
          result["signal"])

    check(f"Score in [0, 100]",
          0 <= result["score"] <= 100, result["score"])

    check(f"Confidence is valid",
          result["confidence"] in ("STRONG", "MODERATE", "WEAK"),
          result["confidence"])

    check(f"At least 1 reason provided",
          len(result["reasons"]) >= 1,
          len(result["reasons"]))

    signal_match = result["signal"] == expected_signal
    check(f"Signal == {expected_signal}",
          signal_match, result["signal"],
          f"score={result['score']}")

    # Signal direction score consistency
    if result["signal"] == "BUY":
        check("BUY score >= 65",
              result["score"] >= 65, result["score"])
    elif result["signal"] == "SELL":
        check("SELL score <= 35",
              result["score"] <= 35, result["score"])
    else:
        check("HOLD score in [36, 64]",
              36 <= result["score"] <= 64, result["score"])

    section("Signal Output")
    print(f"    Signal:     {result['signal']}")
    print(f"    Score:      {result['score']}/100")
    print(f"    Confidence: {result['confidence']}")
    print(f"    Risk:       {result['risk']}")
    print(f"    Reasons:")
    for r in result["reasons"]:
        print(f"      • {r}")

    return result


# ── ADDITIONAL UNIT TESTS ──────────────────────────────────────

def run_unit_tests():
    print(f"\n{'═'*60}")
    print(f"  🔬  UNIT TESTS — Edge Cases & Math Correctness")
    print(f"{'═'*60}")

    section("RSI Edge Cases")

    # Flat price series → RSI should be 50 (no change)
    flat = pd.Series([10.0] * 50)
    rsi_flat = indicators.compute_rsi(flat)
    check("Flat price → RSI near 50 (no momentum)",
          40 <= rsi_flat <= 60, rsi_flat)

    # All up → RSI near 100
    all_up = pd.Series(range(1, 51, 1), dtype=float)
    rsi_up = indicators.compute_rsi(all_up)
    check("All-up prices → RSI > 80",
          rsi_up > 80, rsi_up)

    # All down → RSI near 0
    all_down = pd.Series(range(50, 0, -1), dtype=float)
    rsi_down = indicators.compute_rsi(all_down)
    check("All-down prices → RSI < 20",
          rsi_down < 20, rsi_down)

    section("MACD Math")

    # MACD with fast > slow → should be positive when price trends up
    trend_up = pd.Series(np.linspace(10, 30, 60))
    macd_line, macd_sig, macd_hist = indicators.compute_macd(trend_up)
    check("Uptrend MACD line > 0",
          macd_line > 0, round(macd_line, 4))
    check("Uptrend MACD histogram > 0",
          macd_hist > 0, round(macd_hist, 4))

    trend_down = pd.Series(np.linspace(30, 10, 60))
    macd_line_d, _, macd_hist_d = indicators.compute_macd(trend_down)
    check("Downtrend MACD line < 0",
          macd_line_d < 0, round(macd_line_d, 4))

    section("Bollinger Bands")

    # Price at exactly SMA → %B should be ~0.5
    sma_price = pd.Series([10.0] * 18 + [10.5] + [10.0])  # tiny spike, then back
    bb = indicators.compute_bollinger(sma_price)
    check("BB upper > BB mid > BB lower",
          bb["upper"] > bb["mid"] > bb["lower"],
          f"{bb['upper']:.4f}/{bb['mid']:.4f}/{bb['lower']:.4f}")

    # Verify band math: mid should be 20-period SMA
    series = pd.Series(np.linspace(8, 12, 60))
    bb2 = indicators.compute_bollinger(series)
    expected_mid = float(series.rolling(20).mean().iloc[-1])
    check(f"BB mid matches 20-period SMA ({expected_mid:.4f})",
          abs(bb2["mid"] - expected_mid) < 0.0001,
          bb2["mid"])

    section("Volume Analysis")

    # Spike detection: last bar 3× average
    vol_normal = pd.Series([100_000.0] * 19 + [300_000.0])
    vol_result = indicators.compute_volume_analysis(vol_normal)
    check("Volume 3× avg → is_spike = True",
          vol_result["is_spike"], vol_result["ratio"])
    check("Volume ratio ≈ 3.0",
          2.9 <= vol_result["ratio"] <= 3.1, vol_result["ratio"])

    # No spike
    vol_flat = pd.Series([100_000.0] * 20)
    vol_flat_result = indicators.compute_volume_analysis(vol_flat)
    check("Flat volume → is_spike = False",
          not vol_flat_result["is_spike"], vol_flat_result["ratio"])

    section("EMA vs SMA Difference")

    data = pd.Series(np.linspace(10, 20, 60))
    ema9  = indicators.compute_ema(data, 9)
    ema21 = indicators.compute_ema(data, 21)
    sma50 = indicators.compute_sma(data, 50)

    check("EMA9 > EMA21 in uptrend (faster EMA reacts first)",
          ema9 > ema21, f"EMA9={ema9:.4f} EMA21={ema21:.4f}")
    check("SMA50 < EMA9 in uptrend (SMA lags most)",
          sma50 < ema9, f"SMA50={sma50:.4f} EMA9={ema9:.4f}")

    section("ATR Positivity")

    df_test = make_uptrend()
    atr = indicators.compute_atr(df_test["High"], df_test["Low"], df_test["Close"])
    check("ATR is positive",  atr > 0,  atr)
    check("ATR is not NaN",   not math.isnan(atr))
    check("ATR < price range",
          atr < (df_test["High"].max() - df_test["Low"].min()),
          round(atr, 4))


# ── MAIN ─────────────────────────────────────────────────────

def main():
    print(f"\n{Style.BRIGHT}{'═'*60}")
    print(f"  📈  TRADING BOT BACKTEST  —  Indicator & Signal Validation")
    print(f"{'═'*60}{Style.RESET_ALL}")

    scenarios = [
        ("STRONG UPTREND",    make_uptrend(),         "BUY",  False, "BULL"),
        ("STRONG DOWNTREND",  make_downtrend(),        "SELL", False, "BEAR"),
        ("SIDEWAYS RANGING",  make_sideways(),         "HOLD", False, "SIDE"),
        ("OVERSOLD BOUNCE",   make_oversold_bounce(),  "BUY",  False, "RVSL"),
        ("PENNY VOL SPIKE",   make_penny_spike(),      "BUY",  True,  "PNNY"),
    ]

    scenario_results = []
    for name, df, expected, is_penny, ticker in scenarios:
        result = run_scenario(name, df, expected, is_penny=is_penny, ticker=ticker)
        scenario_results.append((name, expected, result["signal"], result["score"]))

    run_unit_tests()

    # ── FINAL SCORECARD ───────────────────────────────────────
    print(f"\n{'═'*60}")
    print(f"  {Style.BRIGHT}📋  FINAL SCORECARD{Style.RESET_ALL}")
    print(f"{'═'*60}")

    print(f"\n  Scenarios:")
    all_signals_correct = True
    for name, expected, actual, score in scenario_results:
        ok = expected == actual
        if not ok:
            all_signals_correct = False
        status = PASS if ok else FAIL
        print(f"    {status}  {name:<25}  expected={expected:<4}  got={actual:<4}  score={score}/100")

    print(f"\n  Unit Tests:")
    pct = checks_pass / checks_run * 100 if checks_run else 0
    color = Fore.GREEN if checks_fail == 0 else Fore.RED
    print(f"    {color}{Style.BRIGHT}{checks_pass}/{checks_run} checks passed  ({pct:.0f}%){Style.RESET_ALL}")
    if checks_fail > 0:
        print(f"    {Fore.RED}{checks_fail} check(s) FAILED — review output above{Style.RESET_ALL}")

    print(f"\n{'═'*60}")
    overall_ok = checks_fail == 0 and all_signals_correct
    if overall_ok:
        print(f"  {Fore.GREEN}{Style.BRIGHT}✅  ALL TESTS PASSED — Bot indicators verified{Style.RESET_ALL}")
    else:
        print(f"  {Fore.RED}{Style.BRIGHT}❌  SOME TESTS FAILED — review above for details{Style.RESET_ALL}")
    print(f"{'═'*60}\n")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
