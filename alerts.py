# ============================================================
# ALERT FORMATTING & OUTPUT
# Console (colorized) + file logging
# ============================================================

import os
import datetime
from colorama import Fore, Back, Style, init

init(autoreset=True)

_SIGNAL_COLORS = {
    "BUY":  Fore.GREEN  + Style.BRIGHT,
    "SELL": Fore.RED    + Style.BRIGHT,
    "HOLD": Fore.YELLOW,
}

_CONF_COLORS = {
    "STRONG":   Style.BRIGHT,
    "MODERATE": "",
    "WEAK":     Style.DIM,
}

_RISK_COLORS = {
    "LOW":    Fore.GREEN,
    "MEDIUM": Fore.YELLOW,
    "HIGH":   Fore.RED,
}


def _bar(score: int, width: int = 20) -> str:
    """ASCII progress bar representing signal score."""
    filled = round(score / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    if score >= 65:
        color = Fore.GREEN
    elif score <= 35:
        color = Fore.RED
    else:
        color = Fore.YELLOW
    return color + bar + Style.RESET_ALL + f" {score}/100"


def format_alert(result: dict) -> str:
    """Format a single ticker result for console output."""
    sig   = result["signal"]
    conf  = result["confidence"]
    risk  = result["risk"]
    ind   = result["indicators"]
    price = ind["price"]
    lines = []

    sig_col  = _SIGNAL_COLORS.get(sig, "")
    conf_col = _CONF_COLORS.get(conf, "")
    risk_col = _RISK_COLORS.get(risk, "")

    penny_tag = " [PENNY]" if result["is_penny"] else ""
    lines.append(
        f"\n{'─'*58}\n"
        f"  {sig_col}{conf} {sig}{Style.RESET_ALL}  "
        f"│  {Fore.CYAN}{Style.BRIGHT}{result['ticker']}{penny_tag}{Style.RESET_ALL}  "
        f"│  ${price:.4f}"
    )
    lines.append(f"  Score: {_bar(result['score'])}")
    lines.append(
        f"  Risk: {risk_col}{risk}{Style.RESET_ALL}  "
        f"│  Vol {ind['volume_ratio']:.1f}x avg"
        f"{'  🔥 SPIKE' if ind['volume_spike'] else ''}"
    )

    # Key indicators row
    lines.append(
        f"  RSI {ind['rsi']:.1f}  │  "
        f"MACD {ind['macd']:+.4f}  │  "
        f"B% {ind['bb_pct_b']:.2f}  │  "
        f"EMA9 {ind['ema_9']:.3f}"
    )

    # Reasons
    if result["reasons"]:
        lines.append(f"  {'─'*54}")
        for r in result["reasons"]:
            lines.append(f"   • {r}")

    return "\n".join(lines)


def print_header(scan_num: int, ticker_count: int):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"\n{Back.BLUE}{Style.BRIGHT}"
        f"  📈 TRADING SIGNAL BOT  │  Scan #{scan_num}  │  {ts}  │  {ticker_count} tickers  "
        f"{Style.RESET_ALL}"
    )


def print_summary_table(results: list):
    """Print a compact summary table of all results."""
    from tabulate import tabulate
    rows = []
    for r in results:
        ind = r["indicators"]
        sig_col = _SIGNAL_COLORS.get(r["signal"], "")
        rows.append([
            f"{Fore.CYAN}{r['ticker']}{Style.RESET_ALL}",
            f"${ind['price']:.4f}",
            f"{sig_col}{r['signal']}{Style.RESET_ALL}",
            f"{r['score']}/100",
            r["confidence"],
            f"{ind['rsi']:.1f}",
            f"{ind['volume_ratio']:.1f}x",
            f"{'⚡' if ind['volume_spike'] else ''}",
            f"{_RISK_COLORS.get(r['risk'], '')}{r['risk']}{Style.RESET_ALL}",
        ])

    headers = ["Ticker", "Price", "Signal", "Score", "Confidence", "RSI", "Vol", "Spike", "Risk"]
    print("\n" + tabulate(rows, headers=headers, tablefmt="simple"))


def log_to_file(result: dict, log_file: str):
    """Append alert to log file."""
    ts = datetime.datetime.now().isoformat()
    ind = result["indicators"]
    line = (
        f"{ts} | {result['ticker']} | {result['signal']} | "
        f"Score={result['score']} | Conf={result['confidence']} | "
        f"Price=${ind['price']:.4f} | RSI={ind['rsi']:.1f} | "
        f"Vol={ind['volume_ratio']:.1f}x | Risk={result['risk']} | "
        f"Reasons: {'; '.join(result['reasons'])}\n"
    )
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line)
