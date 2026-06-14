# ============================================================
# OPTIONS SUGGESTIONS  (calls / puts with price targets)
#
# Turns a directional stock signal into a concrete options play:
#   BUY  signal -> CALL    SELL signal -> PUT
#
# Pipeline:
#   1. Pick an expiry near OPTIONS_TARGET_DTE.
#   2. Pick the strike whose Black-Scholes delta is closest to
#      OPTIONS_TARGET_DELTA (≈ATM by default), among liquid contracts.
#   3. Reprice that contract with Black-Scholes at the underlying's
#      stop / TP1 / TP2 (from the stock trade plan), stepping time
#      forward by OPTIONS_HOLD_DAYS so theta is accounted for.
#   => entry (buy at ask), stop, TP1, TP2 in OPTION dollars, plus
#      breakeven, delta, IV, and max risk per contract.
#
# HONESTY: the calibrated % on the stock signal is the probability
# the UNDERLYING reaches its target — not the option's P&L. Options
# add IV-crush and theta the stock backtest does not model, so these
# option prices are Black-Scholes ESTIMATES (constant-IV), and real
# fills differ. Liquidity (spread / open interest) is gated. Not
# financial advice.
# ============================================================

from __future__ import annotations

import datetime
import math

import config

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None


# ── BLACK-SCHOLES (pure stdlib) ───────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S: float, K: float, T: float, sigma: float, kind: str,
             r: float = None) -> float:
    """Black-Scholes price for a European call/put. T in years."""
    r = config.RISK_FREE_RATE if r is None else r
    if T <= 0 or sigma <= 0:                      # at/after expiry -> intrinsic
        return max(0.0, (S - K) if kind == "call" else (K - S))
    srt = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / srt
    d2 = d1 - srt
    if kind == "call":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_delta(S: float, K: float, T: float, sigma: float, kind: str,
             r: float = None) -> float:
    r = config.RISK_FREE_RATE if r is None else r
    if T <= 0 or sigma <= 0:
        intrinsic = (S > K) if kind == "call" else (S < K)
        return (1.0 if kind == "call" else -1.0) if intrinsic else 0.0
    srt = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / srt
    return _norm_cdf(d1) if kind == "call" else _norm_cdf(d1) - 1.0


# ── EXPIRY / STRIKE SELECTION ─────────────────────────────────

def _pick_expiry(expiries: list[str], today: datetime.date) -> tuple[str, int] | None:
    """Choose the expiry whose DTE is closest to the target, within bounds."""
    scored = []
    for e in expiries:
        try:
            d = datetime.datetime.strptime(e, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (d - today).days
        if dte < config.OPTIONS_MIN_DTE:
            continue
        scored.append((e, dte))
    if not scored:
        return None
    in_window = [s for s in scored if s[1] <= config.OPTIONS_MAX_DTE]
    pool = in_window or scored
    best = min(pool, key=lambda s: abs(s[1] - config.OPTIONS_TARGET_DTE))
    return best


def _num(row, key) -> float:
    """Read a numeric chain field, treating NaN/None/'' as 0."""
    v = row.get(key)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(v) else v


def _liquid(row) -> bool:
    bid = _num(row, "bid")
    ask = _num(row, "ask")
    oi  = int(_num(row, "openInterest"))
    vol = int(_num(row, "volume"))
    if bid <= 0 or ask <= 0:
        return False
    mid = (bid + ask) / 2
    if mid <= 0:
        return False
    spread_pct = (ask - bid) / mid * 100
    if spread_pct > config.OPTIONS_MAX_SPREAD_PCT:
        return False
    return oi >= config.OPTIONS_MIN_OPEN_INT or vol > 0


# ── MAIN ──────────────────────────────────────────────────────

def suggest(result: dict) -> dict | None:
    """Return an options play for a stock signal result, or None.

    ``result`` is a scanner result (must carry signal, indicators.price,
    indicators.atr and a trade_plan). Returns None for HOLD, missing data,
    no liquid contract, or if yfinance/options are unavailable.
    """
    if not config.OPTIONS_ENABLED or yf is None:
        return None
    signal = result.get("signal")
    if signal not in ("BUY", "SELL"):
        return None
    plan = result.get("trade_plan")
    ind = result.get("indicators", {})
    spot = float(ind.get("price") or result.get("price") or 0)  # rich or flat dict
    if not plan or spot <= 0:
        return None

    kind = "call" if signal == "BUY" else "put"
    ticker = result.get("ticker")

    try:
        tk = yf.Ticker(ticker)
        expiries = list(tk.options or [])
    except Exception:
        return None
    if not expiries:
        return None

    picked = _pick_expiry(expiries, datetime.date.today())
    if not picked:
        return None
    expiry, dte = picked
    T = dte / 365.0

    try:
        chain = tk.option_chain(expiry)
        df = chain.calls if kind == "call" else chain.puts
    except Exception:
        return None
    if df is None or df.empty:
        return None

    # Candidate strikes within a sane window around spot, liquid only.
    lo, hi = spot * 0.6, spot * 1.4
    target_delta = config.OPTIONS_TARGET_DELTA * (1 if kind == "call" else -1)
    best = None
    for _, row in df.iterrows():
        K = float(row["strike"])
        if not (lo <= K <= hi):
            continue
        iv = _num(row, "impliedVolatility")
        if not (0.01 < iv < 5.0):
            continue
        if not _liquid(row):
            continue
        delta = bs_delta(spot, K, T, iv, kind)
        score = abs(delta - target_delta)
        if best is None or score < best[0]:
            best = (score, K, iv, row, delta)

    if best is None:
        return {"available": False, "kind": kind, "expiry": expiry, "dte": dte,
                "note": "No liquid contract near target delta (wide spreads / thin OI)."}

    _, K, iv, row, delta = best
    bid, ask = _num(row, "bid"), _num(row, "ask")
    mid = round((bid + ask) / 2, 2)
    entry = round(ask, 2)                      # buy-to-open pays the ask

    # Targets are scaled to the OPTION's horizon, not the 5-minute scalp plan.
    # The stock trade plan's ATR is intraday (~0.3% moves) — far too small to beat
    # option theta/spread over a multi-day hold. Instead size the underlying
    # targets to the implied move: one standard deviation over the hold,
    #   σ_hold = spot · IV · √(hold/365).
    # TP1 = +1σ, TP2 = +2σ, stop = −1σ (a 1:1 / 2:1 swing in option terms).
    hold = min(config.OPTIONS_HOLD_DAYS, max(dte - 1, 0))
    T_rem = max((dte - hold), 0) / 365.0
    sign = 1 if kind == "call" else -1
    sigma_hold = spot * iv * math.sqrt(max(hold, 1) / 365.0)
    under_tp1  = spot + sign * 1.0 * sigma_hold
    under_tp2  = spot + sign * 2.0 * sigma_hold
    under_stop = spot - sign * 1.0 * sigma_hold

    def price_at(under_px: float) -> float:
        return round(bs_price(under_px, K, T_rem, iv, kind), 2)

    opt_stop = price_at(under_stop)
    opt_tp1  = price_at(under_tp1)
    opt_tp2  = price_at(under_tp2)

    breakeven = round(K + entry, 2) if kind == "call" else round(K - entry, 2)
    risk_per_contract = round(entry * 100, 2)         # premium paid, max loss if held
    # Modeled return at each target, relative to the entry premium.
    def ret(px):
        return round((px - entry) / entry * 100, 1) if entry > 0 else 0.0

    moneyness = "ITM" if bool(row.get("inTheMoney")) else "OTM"

    return {
        "available": True,
        "kind": kind,                  # "call" | "put"
        "ticker": ticker,
        "contract": str(row.get("contractSymbol") or ""),
        "expiry": expiry,
        "dte": dte,
        "strike": K,
        "moneyness": moneyness,
        "spot": round(spot, 2),
        "iv": round(iv * 100, 1),      # %
        "delta": round(delta, 2),
        "bid": round(bid, 2),
        "ask": round(ask, 2),
        "mid": mid,
        "open_interest": int(_num(row, "openInterest")),
        "volume": int(_num(row, "volume")),
        # The plan, in OPTION dollars (per share; ×100 per contract):
        "entry": entry,                # buy-to-open at/under this
        "stop": opt_stop,              # cut the option here (underlying hit its stop)
        "tp1": opt_tp1, "tp1_ret_pct": ret(opt_tp1),   # sell partial
        "tp2": opt_tp2, "tp2_ret_pct": ret(opt_tp2),   # runner
        "breakeven": breakeven,        # underlying price needed at expiry to break even
        "risk_per_contract": risk_per_contract,
        "hold_days_modeled": hold,
        "implied_move_1sigma": round(sigma_hold, 2),
        "underlying_targets": {           # swing levels (implied-move scaled, NOT the scalp plan)
            "spot": round(spot, 2),
            "tp1": round(under_tp1, 2),
            "tp2": round(under_tp2, 2),
            "stop": round(under_stop, 2),
        },
        "caveat": ("Targets are scaled to a ~1σ implied move over the hold; option "
                   "prices are a Black-Scholes estimate at constant IV. The calibrated % is the "
                   "UNDERLYING's hit-rate, not the option's — IV crush and theta can "
                   "lose money even if the stock moves your way. Verify the live "
                   "bid/ask before trading."),
    }


def format_text(opt: dict) -> str:
    """One-block human summary of an options suggestion."""
    if not opt:
        return "No options suggestion (HOLD or data unavailable)."
    if not opt.get("available"):
        return f"{opt.get('kind','option').upper()} {opt.get('expiry','')}: {opt.get('note','no contract')}"
    k = opt["kind"].upper()
    ut = opt["underlying_targets"]
    lines = [
        f"{k} · {opt['ticker']} {opt['strike']:g} {opt['expiry']} ({opt['dte']}DTE, "
        f"{opt['moneyness']}, Δ{opt['delta']:+.2f}, IV {opt['iv']:.0f}%)",
        f"  BUY  ≤ ${opt['entry']:.2f}  (bid ${opt['bid']:.2f} / ask ${opt['ask']:.2f}; "
        f"${opt['risk_per_contract']:,.0f}/contract max risk)",
        f"  SELL TP1 ${opt['tp1']:.2f} ({opt['tp1_ret_pct']:+.0f}%) · "
        f"TP2 ${opt['tp2']:.2f} ({opt['tp2_ret_pct']:+.0f}%)",
        f"  STOP ${opt['stop']:.2f}   ·   breakeven underlying ${opt['breakeven']:.2f}",
        f"  targets assume stock {ut['spot']:.2f} → TP1 {ut['tp1']:.2f} / TP2 {ut['tp2']:.2f}, "
        f"stop {ut['stop']:.2f} (±1σ ≈ ${opt['implied_move_1sigma']:.2f} over {opt['hold_days_modeled']:.0f}d)",
        f"  ⚠ {opt['caveat']}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    import scanner
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    r = scanner.scan_ticker(ticker)
    if not r:
        print(f"No data for {ticker}")
        sys.exit(1)
    print(f"{ticker}: {r['signal']} score={r['score']} conf={r.get('confidence_pct')}%")
    print(format_text(suggest(r)))
