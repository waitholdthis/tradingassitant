# ============================================================
# MOBILE PUSH NOTIFICATIONS
# Pushes BUY/SELL alerts to your phone via ntfy, Pushover,
# and/or Telegram, with a trade plan (stop / target / size)
# computed by trading_assistant.risk.
#
# Channels are configured in config.py (environment variables).
# All sends are fail-safe: errors are logged, never raised into
# the scan loop.
# ============================================================

import datetime
import json
import logging
import threading
import time
import urllib.parse
import urllib.request

import config
from signals import build_trade_plan as _levels
from trading_assistant.risk import fixed_fractional_size

log = logging.getLogger("notify")

_TIMEOUT = 10          # seconds per HTTP request
_RETRIES = 2           # extra attempts per channel after a failure

# ── COOLDOWN (shared across main.py loop and dashboard scans) ─
_cooldown_lock = threading.Lock()
_last_pushed: dict[str, datetime.datetime] = {}


def _in_cooldown(ticker: str, signal: str) -> bool:
    key = f"{ticker}:{signal}"
    with _cooldown_lock:
        last = _last_pushed.get(key)
    if last is None:
        return False
    elapsed = (datetime.datetime.now() - last).total_seconds() / 60
    return elapsed < config.ALERT_COOLDOWN_MINUTES


def _mark_pushed(ticker: str, signal: str):
    with _cooldown_lock:
        _last_pushed[f"{ticker}:{signal}"] = datetime.datetime.now()


# ── RESULT ACCESS (handles both scanner results and dashboard dicts) ─

def _get(result: dict, key: str, default=0.0):
    """Read a field from a rich scanner result or a flattened dashboard dict."""
    if key in result:
        return result[key]
    return result.get("indicators", {}).get(key, default)


# ── TRADE PLAN ────────────────────────────────────────────────

def build_trade_plan(price: float, atr: float, signal: str) -> dict | None:
    """Trade levels (from signals.build_trade_plan) plus position sizing.

    Adds ``shares`` and ``risk_dollars`` by risking ``RISK_PER_TRADE`` of
    ``ACCOUNT_EQUITY`` to the stop. Levels themselves are defined in one place
    (signals.py) so alerts, the dashboard, and calibration never diverge.
    """
    plan = _levels(price, atr, signal)
    if plan is None:
        return None
    risk = plan["risk_per_share"]
    shares = fixed_fractional_size(
        config.ACCOUNT_EQUITY, price, config.RISK_PER_TRADE, stop_distance=risk
    )
    return {
        **plan,
        "target": plan["tp1"],   # back-compat alias
        "shares": shares,
        "risk_dollars": round(shares * risk, 2),
    }


# ── MESSAGE FORMATTING ────────────────────────────────────────

def format_message(result: dict) -> tuple[str, str, bool]:
    """Returns (title, body, urgent)."""
    ticker = result["ticker"]
    signal = result["signal"]
    score = result["score"]
    confidence = result.get("confidence", "")
    conf_pct = result.get("confidence_pct")
    price = float(_get(result, "price"))
    atr = float(_get(result, "atr"))
    urgent = confidence == "STRONG"

    # Prefer the measured calibrated probability in the headline when we have it.
    conf_str = (f"{conf_pct:.0f}% hit-rate" if conf_pct is not None
                else f"{confidence}")
    arrow = "▲" if signal == "BUY" else "▼"
    title = f"{arrow} {signal} {ticker} @ ${price:.4g} — {conf_str} ({score}/100)"

    lines = []
    plan = build_trade_plan(price, atr, signal)
    if plan:
        if signal == "BUY":
            lines.append(
                f"Plan: {plan['shares']} sh @ {plan['entry']:.4g}, stop {plan['stop']:.4g}, "
                f"TP1 {plan['tp1']:.4g} / TP2 {plan['tp2']:.4g} (risk ${plan['risk_dollars']:,.0f})"
            )
        else:
            lines.append(
                f"If holding: exit/tighten stop to {plan['stop']:.4g}, "
                f"downside TP1 {plan['tp1']:.4g} / TP2 {plan['tp2']:.4g}"
            )
        if conf_pct is not None:
            lines.append(
                f"Calibrated {conf_pct:.0f}% to TP1 (measured) — pair with the 2:1 "
                f"runner; win-rate alone isn't edge."
            )
    # Options play (call/put + price targets) — best-effort, never fatal.
    if config.OPTIONS_ENABLED:
        try:
            import options as _opt
            o = _opt.suggest(result)
            if o and o.get("available"):
                lines.append(
                    f"{o['kind'].upper()} {o['strike']:g} {o['expiry']} ({o['dte']}DTE): "
                    f"buy ≤ ${o['entry']:.2f}, TP1 ${o['tp1']:.2f} ({o['tp1_ret_pct']:+.0f}%) "
                    f"/ TP2 ${o['tp2']:.2f}, stop ${o['stop']:.2f}"
                )
        except Exception:
            pass

    risk = result.get("risk")
    if risk:
        lines.append(f"Risk: {risk}" + (" [PENNY]" if result.get("is_penny") else ""))
    for reason in result.get("reasons", [])[:4]:
        lines.append(f"• {reason}")
    lines.append("Not financial advice — verify before trading.")
    return title, "\n".join(lines), urgent


# ── CHANNELS ──────────────────────────────────────────────────

def _post(url: str, data: bytes, headers: dict):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        resp.read()


def _send_ntfy(title: str, body: str, urgent: bool):
    url = f"{config.NTFY_SERVER.rstrip('/')}/{config.NTFY_TOPIC}"
    headers = {
        "Title": title.encode("ascii", "ignore").decode(),  # ntfy headers are ASCII
        "Priority": "urgent" if urgent else "high",
        "Tags": "chart_with_upwards_trend" if "BUY" in title else "chart_with_downwards_trend",
    }
    _post(url, body.encode(), headers)


def _send_pushover(title: str, body: str, urgent: bool):
    data = urllib.parse.urlencode({
        "token": config.PUSHOVER_TOKEN,
        "user": config.PUSHOVER_USER,
        "title": title,
        "message": body,
        "priority": 1 if urgent else 0,
    }).encode()
    _post("https://api.pushover.net/1/messages.json", data,
          {"Content-Type": "application/x-www-form-urlencoded"})


def _send_telegram(title: str, body: str, urgent: bool):
    data = json.dumps({
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": f"{title}\n{body}",
        "disable_notification": False,
    }).encode()
    _post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
          data, {"Content-Type": "application/json"})


def enabled_channels() -> list[tuple[str, callable]]:
    channels = []
    if config.NTFY_TOPIC:
        channels.append(("ntfy", _send_ntfy))
    if config.PUSHOVER_TOKEN and config.PUSHOVER_USER:
        channels.append(("pushover", _send_pushover))
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        channels.append(("telegram", _send_telegram))
    return channels


# ── DISPATCH ──────────────────────────────────────────────────

def push_signal(result: dict) -> bool:
    """Push one alert to every enabled channel. Returns True if any send
    succeeded. Never raises."""
    channels = enabled_channels()
    if not channels:
        return False
    try:
        title, body, urgent = format_message(result)
    except Exception:
        log.exception("could not format alert for %s", result.get("ticker"))
        return False

    sent = False
    for name, send in channels:
        for attempt in range(_RETRIES + 1):
            try:
                send(title, body, urgent)
                sent = True
                break
            except Exception as e:
                if attempt < _RETRIES:
                    time.sleep(2 ** attempt)
                else:
                    log.warning("push via %s failed: %s", name, e)
    return sent


def _is_actionable(result: dict) -> bool:
    signal = result.get("signal")
    score = result.get("score", 50)
    if signal == "BUY":
        return score >= config.MIN_SIGNAL_SCORE
    if signal == "SELL":
        return score <= 100 - config.MIN_SIGNAL_SCORE
    return False


def dispatch(results: list[dict]) -> int:
    """Filter scan results to actionable signals, apply the cooldown, and
    push each one. Returns the number of alerts pushed."""
    if not enabled_channels():
        return 0
    pushed = 0
    for result in results:
        if not _is_actionable(result):
            continue
        ticker, signal = result["ticker"], result["signal"]
        if _in_cooldown(ticker, signal):
            continue
        if push_signal(result):
            _mark_pushed(ticker, signal)
            pushed += 1
    return pushed


def send_test() -> bool:
    """Send a test notification to verify channel setup."""
    channels = enabled_channels()
    if not channels:
        print("No push channels configured. Set NTFY_TOPIC, PUSHOVER_TOKEN/"
              "PUSHOVER_USER, or TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID.")
        return False
    print(f"Sending test push via: {', '.join(name for name, _ in channels)}")
    ok = push_signal({
        "ticker": "TEST",
        "signal": "BUY",
        "score": 99,
        "confidence": "STRONG",
        "risk": "LOW",
        "reasons": ["This is a test alert from your trading bot"],
        "indicators": {"price": 100.0, "atr": 2.0},
    })
    print("Test push sent — check your phone." if ok else "Test push FAILED — see logs.")
    return ok
