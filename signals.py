# ============================================================
# SIGNAL GENERATION ENGINE  (v4 - Professional Confluence)
#
# Architecture:
#   1. Market regime check (ADX) - only trade real trends
#   2. Primary trend: EMA stack + Supertrend (strongest signals)
#   3. Momentum: RSI + MFI + Williams %R (3 oscillators, vote)
#   4. Volume: OBV + VWAP + Volume ratio (institutional confirms)
#   5. Confirmation: MACD + Stochastic + Bollinger %B
#   6. Candlestick pattern bonus
#   7. Penny stock amplifier
#
# Confluence rule: require 3+ confirming signals before BUY/SELL.
# ADX < 20 with no strong pattern = HOLD (avoid choppy markets).
# ============================================================

from config import RSI_OVERSOLD, RSI_OVERBOUGHT, VOLUME_SPIKE_MULT

# Stops sit STOP_ATR_MULT ATRs from entry (= 1R). TP1 is the first/partial
# target; TP2 is the runner. Calibration (calibration.py) measures the real
# hit-rate of TP1 — that is what the engine reports as "confidence".
STOP_ATR_MULT     = 2.0
STOP_PCT_FALLBACK = 0.05   # used when ATR is unavailable
TP1_RR            = 1.0     # first target / take partial (≈1:1)
TP2_RR            = 2.0     # runner — where the positive expectancy lives


def build_trade_plan(price: float, atr: float, signal: str) -> dict | None:
    """Entry, stop, and two take-profit targets for a signal.

    Risk (R) is STOP_ATR_MULT ATRs (falling back to STOP_PCT_FALLBACK of price).
    Targets sit at 2R and 3R for a 2:1 / 3:1 reward:risk. Returns None for HOLD
    or non-positive price. This is the single source of truth for trade levels —
    notify.py, the dashboard, and the backtest calibration all use it.
    """
    if price <= 0 or signal not in ("BUY", "SELL"):
        return None
    risk = atr * STOP_ATR_MULT if atr and atr > 0 else price * STOP_PCT_FALLBACK
    direction = 1 if signal == "BUY" else -1
    stop = price - direction * risk
    tp1  = price + direction * risk * TP1_RR
    tp2  = price + direction * risk * TP2_RR
    return {
        "entry":     round(price, 4),
        "stop":      round(stop, 4),
        "tp1":       round(tp1, 4),
        "tp2":       round(tp2, 4),
        "risk_per_share": round(risk, 4),
        "rr":        TP1_RR,
    }


def _trend_score(ind):
    p, e9, e21 = ind["price"], ind["ema_9"], ind["ema_21"]
    m, ms = ind["macd"], ind["macd_signal"]
    t = 0
    if p > e9 > e21:    t += 2
    elif p > e9:         t += 1
    elif p < e9 < e21:  t -= 2
    elif p < e9:        t -= 1
    if m > 0 and ms > 0:    t += 1
    elif m < 0 and ms < 0:  t -= 1
    return max(-3, min(3, t))


def generate_signal(ind, ticker, is_penny=False):
    score   = 50
    reasons = []
    price   = ind["price"]
    adx     = ind["adx"]
    t       = _trend_score(ind)
    is_up   = t >= 2
    is_down = t <= -2
    macd_turning_up = ind["macd_hist"] > 0
    confirming_buys  = 0
    confirming_sells = 0

    # ── STEP 1: MARKET REGIME (ADX filter) ────────────────────
    # ADX < 20: ranging/choppy market. Signals are noise.
    # ADX 20-25: weak trend. Light weighting.
    # ADX 25+: confirmed trend. Full signal weight.
    if adx >= 25:
        regime = "TRENDING"
        adx_weight = 1.0
    elif adx >= 20:
        regime = "WEAK_TREND"
        adx_weight = 0.6
    else:
        regime = "RANGING"
        adx_weight = 0.3
        reasons.append(f"ADX={adx:.1f} — ranging market, signals dampened")

    # ── STEP 2: SUPERTREND (strongest trend signal) ────────────
    st_dir = ind["supertrend_dir"]
    if st_dir == 1:
        delta = 14 * adx_weight
        score += delta
        confirming_buys += 1
        reasons.append(f"Supertrend BULLISH (ADX={adx:.1f}) — price above dynamic support")
    else:
        delta = 14 * adx_weight
        score -= delta
        confirming_sells += 1
        reasons.append(f"Supertrend BEARISH (ADX={adx:.1f}) — price below dynamic resistance")

    # DI crossover strength
    if ind["plus_di"] > ind["minus_di"] and adx >= 20:
        score += 5 * adx_weight
        confirming_buys += 1
        reasons.append(f"+DI {ind['plus_di']:.1f} > -DI {ind['minus_di']:.1f} — buyers dominating")
    elif ind["minus_di"] > ind["plus_di"] and adx >= 20:
        score -= 5 * adx_weight
        confirming_sells += 1
        reasons.append(f"-DI {ind['minus_di']:.1f} > +DI {ind['plus_di']:.1f} — sellers dominating")

    # ── STEP 3: EMA TREND STRUCTURE ───────────────────────────
    e9, e21 = ind["ema_9"], ind["ema_21"]
    if price > e9 > e21:
        score += 12 * adx_weight
        confirming_buys += 1
        reasons.append("Price > EMA9 > EMA21 — perfect bullish stack")
    elif price < e9 < e21:
        score -= 12 * adx_weight
        confirming_sells += 1
        reasons.append("Price < EMA9 < EMA21 — perfect bearish stack")
    elif price > e9:
        score += 5 * adx_weight
        reasons.append("Price above EMA9 — short-term bullish")
    elif price < e9:
        score -= 5 * adx_weight
        reasons.append("Price below EMA9 — short-term bearish")

    # ── STEP 4: VWAP (institutional benchmark) ────────────────
    if ind["above_vwap"]:
        score += 7 * adx_weight
        confirming_buys += 1
        reasons.append(f"Price {ind['vwap_pct']:+.1f}% above VWAP — institutional buy side")
    else:
        score -= 7 * adx_weight
        confirming_sells += 1
        reasons.append(f"Price {ind['vwap_pct']:+.1f}% below VWAP — institutional sell side")

    # ── STEP 5: OBV (volume trend confirmation) ────────────────
    if ind["obv_above_ema"] and ind["obv_slope"] > 0:
        score += 6
        confirming_buys += 1
        reasons.append("OBV rising above EMA — accumulation confirmed")
    elif not ind["obv_above_ema"] and ind["obv_slope"] < 0:
        score -= 6
        confirming_sells += 1
        reasons.append("OBV falling below EMA — distribution confirmed")
    elif ind["obv_above_ema"] and ind["obv_slope"] < 0:
        reasons.append("OBV divergence warning — price up but volume fading")
    elif not ind["obv_above_ema"] and ind["obv_slope"] > 0:
        score += 3
        reasons.append("OBV turning up — early accumulation signal")

    # ── STEP 6: MOMENTUM OSCILLATORS (3-way vote) ─────────────
    osc_buy = 0
    osc_sell = 0

    # RSI
    rsi = ind["rsi"]
    if is_up and rsi > RSI_OVERBOUGHT:
        osc_buy += 1
        reasons.append(f"RSI {rsi:.1f} overbought confirms uptrend momentum")
    elif is_down and rsi < RSI_OVERSOLD:
        if macd_turning_up:
            osc_buy += 2
            score += 10
            reasons.append(f"RSI {rsi:.1f} oversold + MACD turning = REVERSAL DIVERGENCE")
        else:
            osc_sell += 1
            reasons.append(f"RSI {rsi:.1f} oversold but MACD still falling (falling knife)")
    elif rsi < RSI_OVERSOLD:
        osc_buy += 2
        reasons.append(f"RSI {rsi:.1f} deeply oversold — BUY pressure")
    elif rsi > RSI_OVERBOUGHT:
        osc_sell += 2
        reasons.append(f"RSI {rsi:.1f} overbought — SELL pressure")
    elif rsi < 40:
        osc_buy += 1
        reasons.append(f"RSI {rsi:.1f} approaching oversold")
    elif rsi > 60:
        osc_sell += 1
        reasons.append(f"RSI {rsi:.1f} approaching overbought")

    # MFI (volume-weighted RSI — harder to fake)
    mfi = ind["mfi"]
    if mfi < 20:
        osc_buy += 2
        reasons.append(f"MFI {mfi:.1f} oversold — real money flowing in")
    elif mfi > 80:
        osc_sell += 2
        reasons.append(f"MFI {mfi:.1f} overbought — money flowing out")
    elif mfi < 40:
        osc_buy += 1
        reasons.append(f"MFI {mfi:.1f} weak — potential accumulation")
    elif mfi > 60:
        osc_sell += 1
        reasons.append(f"MFI {mfi:.1f} elevated — distribution possible")

    # Williams %R (early warning oscillator)
    wr = ind["williams_r"]
    if wr > -20:
        osc_sell += 1
        reasons.append(f"Williams %R {wr:.1f} overbought zone")
    elif wr < -80:
        osc_buy += 1
        reasons.append(f"Williams %R {wr:.1f} oversold zone")

    # Apply oscillator vote score
    osc_net = osc_buy - osc_sell
    osc_delta = osc_net * 4
    score += osc_delta
    if osc_buy >= 3:
        confirming_buys += 1
    if osc_sell >= 3:
        confirming_sells += 1

    # ── STEP 7: MACD ──────────────────────────────────────────
    if ind["macd_hist"] > 0 and ind["macd"] > ind["macd_signal"]:
        score += 7
        confirming_buys += 1
        reasons.append("MACD bullish crossover — momentum rising")
    elif ind["macd_hist"] < 0 and ind["macd"] < ind["macd_signal"]:
        score -= 7
        confirming_sells += 1
        reasons.append("MACD bearish crossover — momentum falling")
    if ind["macd"] > 0 and ind["macd_signal"] > 0:
        score += 4
        reasons.append("MACD above zero — uptrend confirmed")
    elif ind["macd"] < 0 and ind["macd_signal"] < 0:
        score -= 4
        reasons.append("MACD below zero — downtrend confirmed")

    # ── STEP 8: BOLLINGER BANDS ───────────────────────────────
    pct_b = ind["bb_pct_b"]
    if is_up and pct_b > 0.80:
        score += 6
        reasons.append(f"Riding upper Bollinger Band in uptrend (B%={pct_b:.2f}) — breakout")
    elif is_down and pct_b < 0.20:
        if macd_turning_up:
            score += 5
            reasons.append(f"Lower BB + MACD turning (B%={pct_b:.2f}) — reversal zone")
        else:
            score -= 6
            reasons.append(f"Riding lower BB in downtrend (B%={pct_b:.2f}) — breakdown")
    elif pct_b < 0.05:
        score += 8
        reasons.append(f"Price at lower BB (B%={pct_b:.2f}) — mean reversion BUY")
    elif pct_b > 0.95:
        score -= 8
        reasons.append(f"Price at upper BB (B%={pct_b:.2f}) — mean reversion SELL")

    # ── STEP 9: CANDLESTICK PATTERNS ──────────────────────────
    patterns = ind.get("patterns", {})
    pat_score = 0
    for pat, direction in patterns.items():
        if direction == "bullish":
            pat_score += 6
            reasons.append(f"Pattern: {pat.replace('_',' ').title()} (bullish)")
        elif direction == "bearish":
            pat_score -= 6
            reasons.append(f"Pattern: {pat.replace('_',' ').title()} (bearish)")
    score += pat_score

    # ── STEP 10: VOLUME SPIKE CONFIRMATION ────────────────────
    vr = ind["volume_ratio"]
    if vr >= VOLUME_SPIKE_MULT:
        bias = score - 50
        if bias > 0:
            score += 12
            confirming_buys += 1
            reasons.append(f"VOLUME SPIKE {vr:.1f}x — confirms BUY")
        elif bias < 0:
            score -= 12
            confirming_sells += 1
            reasons.append(f"VOLUME SPIKE {vr:.1f}x — confirms SELL")
    elif vr > 1.5:
        adj = 3 if (score - 50) >= 0 else -3
        score += adj
        reasons.append(f"Elevated volume {vr:.1f}x — interest building")

    # ── STEP 11: CONFLUENCE GATE ──────────────────────────────
    # Require minimum 3 confirming signals for BUY/SELL action.
    # This eliminates false positives in choppy / low-ADX markets.
    raw_score = score
    if raw_score > 50:
        if confirming_buys < 3:
            score = min(score, 62)  # Cap below BUY threshold
            reasons.append(f"Confluence gate: only {confirming_buys}/3 required confirms — HOLD")
    elif raw_score < 50:
        if confirming_sells < 3:
            score = max(score, 38)
            reasons.append(f"Confluence gate: only {confirming_sells}/3 required confirms — HOLD")

    # ── STEP 12: PENNY STOCK FILTER ───────────────────────────
    if is_penny:
        if not ind["volume_spike"] and abs(score - 50) < 15:
            score = 50
            reasons.append("Penny stock: weak signal filtered (no volume confirmation)")
        elif ind["volume_spike"]:
            score = 50 + (score - 50) * 1.35
            reasons.append("Penny stock amplifier: 1.35x (confirmed by volume)")

    # ── CLASSIFY ──────────────────────────────────────────────
    score = max(0, min(100, round(score)))
    signal     = "BUY" if score >= 65 else ("SELL" if score <= 35 else "HOLD")
    atr_pct    = ind["atr"] / price * 100 if price > 0 else 0
    risk       = "HIGH" if (is_penny or atr_pct > 5) else ("MEDIUM" if atr_pct > 2 else "LOW")

    trade_plan = build_trade_plan(price, ind.get("atr", 0.0), signal)

    # ── CALIBRATED CONFIDENCE ─────────────────────────────────
    # confidence_pct is the historically MEASURED probability this signal's
    # score bucket reaches its first target (TP1) before its stop — not a
    # label. None when no calibration table exists or the bucket is untrusted;
    # in that case we fall back to the old score-band label and say so.
    confidence_pct, confidence_trusted = _calibrated_confidence(score, signal)
    if confidence_pct is not None and confidence_trusted:
        confidence = _confidence_label(confidence_pct)
        confidence_basis = "calibrated"
    else:
        confidence = "STRONG" if (score >= 80 or score <= 20) else (
            "MODERATE" if (score >= 65 or score <= 35) else "WEAK")
        confidence_basis = "uncalibrated"

    return {
        "ticker":      ticker,
        "signal":      signal,
        "score":       score,
        "confidence":  confidence,
        "confidence_pct":     confidence_pct,     # measured % or None
        "confidence_trusted": confidence_trusted,
        "confidence_basis":   confidence_basis,   # "calibrated" | "uncalibrated"
        "reasons":     reasons,
        "risk":        risk,
        "is_penny":    is_penny,
        "regime":      regime,
        "adx":         adx,
        "confluence":  {"buys": confirming_buys, "sells": confirming_sells},
        "trade_plan":  trade_plan,
        "indicators":  ind,
    }


def _calibrated_confidence(score, signal):
    """Look up measured confidence; lazy import avoids a calibration<->signals
    import cycle. Returns (pct_or_None, trusted)."""
    if signal not in ("BUY", "SELL"):
        return None, False
    try:
        import calibration
        return calibration.confidence_for(score, signal)
    except Exception:
        return None, False


def _confidence_label(pct: float) -> str:
    """Map a measured probability to a label. Bands reflect that, at a 1:1
    first target, ~50% is the realistic ceiling for this engine."""
    if pct >= 60:
        return "STRONG"
    if pct >= 50:
        return "MODERATE"
    return "WEAK"
