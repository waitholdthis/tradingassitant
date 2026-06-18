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
from zoneinfo import ZoneInfo

import scanner
import alerts
import notify
import options
from config import (
    WATCHLIST, SCAN_INTERVAL_SECONDS,
    SHOW_ALL_TICKERS, CLEAR_SCREEN, LOG_FILE,
    MIN_SIGNAL_SCORE, UNIVERSE_SCAN_TIME_ET,
)

_ET = ZoneInfo("America/New_York")


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

    # ── Options suggestion (call/put with price targets) ──────
    if result["signal"] in ("BUY", "SELL"):
        print(f"\n{'─'*58}")
        print(f"  OPTIONS PLAY — {'CALL' if result['signal']=='BUY' else 'PUT'}")
        print(f"{'─'*58}")
        try:
            print(options.format_text(options.suggest(result)))
        except Exception as e:
            print(f"  Options unavailable: {e}")

    ind = result["indicators"]
    print(f"\n{'─'*58}")
    print("  FULL INDICATOR READOUT")
    print(f"{'─'*58}")
    for k, v in ind.items():
        print(f"  {k:<18} {v}")


def run_universe_scan():
    """Run the full-universe top-10 scan, print results, and push alerts."""
    print(f"\n{'═'*58}")
    print("  🌐 FULL UNIVERSE SCAN — Top 10 BUY signals")
    print(f"{'═'*58}")
    top10 = scanner.scan_universe(top_n=10)
    if not top10:
        print("  No qualifying BUY signals found in the universe this run.")
        return
    print(f"\n  Top 10 BUY signals across all US-listed stocks:\n")
    alerts.print_summary_table(top10)
    print()
    for result in top10:
        print(alerts.format_alert(result))
        alerts.log_to_file(result, LOG_FILE)
    pushed = notify.dispatch(top10)
    if pushed:
        print(f"\n  📱 {pushed} alert(s) pushed to your phone.")


def main():
    parser = argparse.ArgumentParser(description="Trading Signal Bot")
    parser.add_argument("--once",   action="store_true", help="Run one scan and exit")
    parser.add_argument("--ticker", type=str,            help="Deep-scan a single ticker")
    parser.add_argument("--top10",  action="store_true",
                        help="Scan all US-listed stocks and show the top 10 BUY signals")
    parser.add_argument("--notify-test", action="store_true",
                        help="Send a test push notification and exit")
    args = parser.parse_args()

    if args.notify_test:
        sys.exit(0 if notify.send_test() else 1)

    if args.top10:
        run_universe_scan()
        return

    channels = [name for name, _ in notify.enabled_channels()]
    print("\n  📈 Trading Signal Bot starting up...")
    print(f"  Watching: {', '.join(WATCHLIST)}")
    print(f"  Scan interval: {SCAN_INTERVAL_SECONDS}s | Min score: {MIN_SIGNAL_SCORE}/100")
    if channels:
        print(f"  📱 Mobile push: {', '.join(channels)}")
    else:
        print("  📱 Mobile push: OFF — set NTFY_TOPIC (see README) to get phone alerts")
    print(f"  🌐 Universe scan: daily at {UNIVERSE_SCAN_TIME_ET} ET")

    if args.ticker:
        deep_scan_ticker(args.ticker)
        return

    _scan_hour, _scan_minute = (int(p) for p in UNIVERSE_SCAN_TIME_ET.split(":"))

    def _universe_scan_due(last_date: datetime.date | None) -> bool:
        now_et = datetime.datetime.now(tz=_ET)
        if now_et.hour < _scan_hour or (now_et.hour == _scan_hour and now_et.minute < _scan_minute):
            return False
        return last_date != now_et.date()

    scan_num = 1
    consecutive_failures = 0
    last_universe_scan_date: datetime.date | None = None

    try:
        while True:
            # ── Scheduled universe scan ───────────────────────
            if _universe_scan_due(last_universe_scan_date):
                try:
                    run_universe_scan()
                    last_universe_scan_date = datetime.datetime.now(tz=_ET).date()
                except Exception as e:
                    print(f"\n  ⚠ Universe scan failed: {e!r}")

            # ── Regular watchlist scan ────────────────────────
            try:
                run_scan(scan_num)
                consecutive_failures = 0
            except Exception as e:
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
