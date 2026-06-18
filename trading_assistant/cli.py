"""Command-line interface.

Examples::

    # Technical snapshot from a CSV (or live via --fetch with yfinance installed)
    python -m trading_assistant analyze --csv data/AAPL.csv
    python -m trading_assistant analyze --fetch AAPL --period 1y

    # Backtest a strategy, compared against buy-and-hold
    python -m trading_assistant backtest --csv data/AAPL.csv --strategy sma
    python -m trading_assistant backtest --demo --strategy ensemble

    # Compare every built-in strategy on the same data
    python -m trading_assistant compare --demo

    # Position sizing
    python -m trading_assistant size --equity 50000 --price 185.5 --atr 3.2
"""

from __future__ import annotations

import argparse
import sys

from .analysis import snapshot
from .backtest import Backtester, buy_and_hold
from .data import OHLCV, fetch_yfinance, load_csv, synthetic_series
from .risk import atr_bracket, atr_position_size, bracket, fixed_fractional_size
from .strategies import BUILTIN_STRATEGIES, make_strategy

STRATEGY_CHOICES = [*BUILTIN_STRATEGIES, "ensemble"]


def _load_series(args: argparse.Namespace) -> OHLCV:
    if getattr(args, "csv", None):
        return load_csv(args.csv, symbol=getattr(args, "symbol", None))
    if getattr(args, "fetch", None):
        return fetch_yfinance(args.fetch, period=getattr(args, "period", "1y"))
    if getattr(args, "demo", False):
        return synthetic_series("DEMO", days=504)
    raise SystemExit("error: provide one of --csv PATH, --fetch SYMBOL, or --demo")


def cmd_analyze(args: argparse.Namespace) -> int:
    series = _load_series(args)
    print(snapshot(series).report())
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    series = _load_series(args)
    strategy = make_strategy(args.strategy)
    bt = Backtester(
        initial_capital=args.capital,
        commission=args.commission,
        slippage_bps=args.slippage,
    )
    result = bt.run(strategy, series)
    print(result.summary())
    bench = buy_and_hold(series, initial_capital=args.capital)
    print(f"\nBenchmark (buy & hold): {bench.total_return:+.2%} total, "
          f"Sharpe {bench.sharpe:.2f}, max DD -{bench.max_drawdown:.2%}")
    edge = result.total_return - bench.total_return
    print(f"Strategy vs benchmark:  {edge:+.2%}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    series = _load_series(args)
    bt = Backtester(initial_capital=args.capital)
    rows = []
    for name in STRATEGY_CHOICES:
        r = bt.run(make_strategy(name), series)
        rows.append((name, r.total_return, r.sharpe, r.max_drawdown, r.win_rate, len(r.closed_trades)))
    bench = buy_and_hold(series, initial_capital=args.capital)
    rows.append(("buy_and_hold", bench.total_return, bench.sharpe, bench.max_drawdown, bench.win_rate, len(bench.closed_trades)))

    rows.sort(key=lambda r: r[2], reverse=True)
    header = f"{'strategy':<14} {'return':>9} {'sharpe':>7} {'max DD':>8} {'win%':>6} {'trades':>7}"
    print(f"Comparison on {series.symbol} ({len(series)} bars, sorted by Sharpe)\n")
    print(header)
    print("-" * len(header))
    for name, ret, sharpe, dd, wr, n in rows:
        print(f"{name:<14} {ret:>+8.1%} {sharpe:>7.2f} {-dd:>+7.1%} {wr:>5.0%} {n:>7}")
    return 0


def cmd_size(args: argparse.Namespace) -> int:
    if args.atr:
        shares = atr_position_size(args.equity, args.price, args.atr,
                                   risk_fraction=args.risk, atr_multiple=args.atr_mult)
        levels = atr_bracket(args.price, args.atr, stop_mult=args.atr_mult, reward_risk=args.reward_risk)
        basis = f"ATR {args.atr:g} x {args.atr_mult:g}"
    else:
        shares = fixed_fractional_size(args.equity, args.price, risk_fraction=args.risk,
                                       stop_distance=args.price * args.stop_pct)
        levels = bracket(args.price, stop_pct=args.stop_pct, reward_risk=args.reward_risk)
        basis = f"{args.stop_pct:.1%} stop"

    value = shares * args.price
    risk_amount = shares * (args.price - levels.stop_loss)
    print(f"Position size for entry at {args.price:.2f} ({basis}, risking {args.risk:.1%} of equity):")
    print(f"  Shares:      {shares}")
    print(f"  Value:       ${value:,.2f} ({value / args.equity:.1%} of equity)")
    print(f"  Stop loss:   {levels.stop_loss:.2f}  (risk ${risk_amount:,.2f})")
    print(f"  Take profit: {levels.take_profit:.2f}  ({args.reward_risk:g}:1 reward:risk)")
    return 0


def _add_data_args(p: argparse.ArgumentParser) -> None:
    src = p.add_argument_group("data source (choose one)")
    src.add_argument("--csv", help="path to an OHLCV CSV file")
    src.add_argument("--fetch", metavar="SYMBOL", help="fetch from Yahoo Finance (needs yfinance + network)")
    src.add_argument("--demo", action="store_true", help="use generated demo data")
    p.add_argument("--symbol", help="symbol label for --csv data")
    p.add_argument("--period", default="1y", help="history window for --fetch (default: 1y)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-assistant",
        description="Technical analysis, strategy backtesting, and risk sizing.",
        epilog="Run a subcommand with -h for its options.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", help="technical snapshot of a symbol")
    _add_data_args(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("backtest", help="backtest a strategy vs buy-and-hold")
    _add_data_args(p)
    p.add_argument("--strategy", choices=STRATEGY_CHOICES, default="sma")
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--commission", type=float, default=1.0, help="cost per order (default: 1.0)")
    p.add_argument("--slippage", type=float, default=5.0, help="slippage in bps (default: 5)")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("compare", help="run all strategies on the same data")
    _add_data_args(p)
    p.add_argument("--capital", type=float, default=100_000.0)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("size", help="position sizing with stop/target levels")
    p.add_argument("--equity", type=float, required=True, help="account equity")
    p.add_argument("--price", type=float, required=True, help="entry price")
    p.add_argument("--risk", type=float, default=0.01, help="fraction of equity at risk (default: 0.01)")
    p.add_argument("--atr", type=float, help="current ATR for volatility-based sizing")
    p.add_argument("--atr-mult", type=float, default=2.0, help="stop distance in ATRs (default: 2)")
    p.add_argument("--stop-pct", type=float, default=0.05, help="stop distance as fraction of price (default: 0.05)")
    p.add_argument("--reward-risk", type=float, default=2.0, help="take-profit ratio (default: 2)")
    p.set_defaults(func=cmd_size)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError, FileNotFoundError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
