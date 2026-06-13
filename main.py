#!/usr/bin/env python3
# ============================================================
# TRADING SIGNAL BOT — MAIN ENTRY POINT
#
# Usage:
#   python main.py              → continuous scan loop
#   python main.py --once       → single scan then exit
#   python main.py --ticker TSLA → single ticker deep scan
#
# Edit config.py to change watchlist, thresholds, intervals
# ============================================================

import os
import sys
import time
import argparse
import datetime

import scanner
import alerts
import notify
from config import (
    WATCHLIST, SCAN_INTERVAL_SECONDS,
    SHOW_ALL_TICKERS, CLEAR_SCREEN, LOG_FILE,
    MIN_SIGNAL_SCORE,
)


def run_scan(scan_num: int):
    if CLEAR_SCREEN:
        os.system("cls" if os.name == "nt" else "clear")

    alerts.print_header(scan_num, len(WATCHLIST))
    print(f"\n  Scanning {len(WATCHLIST)} tickers... ", end="", flush=True)

    results = scanner.scan_all(WATCHLIST, show_all=SHOW_ALL_TICKERS)
    actionable = scanner.get_actionable(results)

    print(f"done. {len(actionable)} signal(s) found.\n")

    # ── Summary table (all tickers) ──────────────────────────
    if results:
        alerts.print_summary_table(results)

    # ── Detailed alerts (BUY/SELL only) ──────────────────────
    if actionable:
        print(f"\n{'═'*58}")
        print(f"  🚨  {len(actionable)} ACTIONABLE SIGNAL(S)")
        print(f"{'═'*58}")
        for result in actionable:
            print(alerts.format_alert(result))
            alerts.log_to_file(result, LOG_FILE)
        scanner.mark_alerts_sent(actionable)
        pushed = notify.dispatch(actionable)
        if pushed:
            print(f"\n  📱 {pushed} alert(s) pushed to your phone.")
    else:
        print(f"\n  No signals above threshold (score ≥ {MIN_SIGNAL_SCORE}) this scan.")

    # ── Next scan countdown ───────────────────────────────────
    next_scan = datetime.datetime.now() + datetime.timedelta(seconds=SCAN_INTERVAL_SECONDS)
    print(f"\n  Next scan at {next_scan.strftime('%H:%M:%S')}  (Ctrl+C to stop)\n")


def deep_scan_ticker(ticker: str):
    """Detailed single-ticker analysis."""
    print(f"\n🔍 Deep scanning {ticker}...\n")
    result = scanner.scan_ticker(ticker.upper())
    if result is None:
        print(f"  Could not fetch data for {ticker}. Check the ticker symbol.")
        return

    print(alerts.format_alert(result))

    ind = result["indicators"]
    print(f"\n{'─'*58}")
    print("  FULL INDICATOR READOUT")
    print(f"{'─'*58}")
    for k, v in ind.items():
        print(f"  {k:<18} {v}")


def main():
    parser = argparse.ArgumentParser(description="Trading Signal Bot")
    parser.add_argument("--once",   action="store_true", help="Run one scan and exit")
    parser.add_argument("--ticker", type=str,            help="Deep-scan a single ticker")
    parser.add_argument("--notify-test", action="store_true",
                        help="Send a test push notification and exit")
    args = parser.parse_args()

    if args.notify_test:
        sys.exit(0 if notify.send_test() else 1)

    channels = [name for name, _ in notify.enabled_channels()]
    print("\n  📈 Trading Signal Bot starting up...")
    print(f"  Watching: {', '.join(WATCHLIST)}")
    print(f"  Scan interval: {SCAN_INTERVAL_SECONDS}s | Min score: {MIN_SIGNAL_SCORE}/100")
    if channels:
        print(f"  📱 Mobile push: {', '.join(channels)}")
    else:
        print("  📱 Mobile push: OFF — set NTFY_TOPIC (see README) to get phone alerts")

    if args.ticker:
        deep_scan_ticker(args.ticker)
        return

    scan_num = 1
    consecutive_failures = 0
    try:
        while True:
            try:
                run_scan(scan_num)
                consecutive_failures = 0
            except Exception as e:
                # Never let one bad scan kill the loop; back off if it keeps failing.
                consecutive_failures += 1
                backoff = min(SCAN_INTERVAL_SECONDS * 2 ** (consecutive_failures - 1), 900)
                print(f"\n  ⚠ Scan #{scan_num} failed ({e!r}); retrying in {backoff:.0f}s")
                time.sleep(backoff)
            scan_num += 1
            if args.once:
                break
            time.sleep(SCAN_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n\n  Bot stopped. Goodbye! 📊\n")


if __name__ == "__main__":
    main()
