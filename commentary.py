# ============================================================
# LLM COMMENTARY LAYER  (optional)
#
# Turns a computed signal into a written, persona-styled note —
# the "elite quant strategist" voice from the project brief —
# but bound HARD to the numbers the engine produced. The model
# is told, in the system prompt, that it may use ONLY the values
# it is given, may not invent data, and must report the MEASURED
# calibrated confidence rather than claim an unearned 80%.
#
# It is strictly optional and fail-safe:
#   - No ANTHROPIC_API_KEY  -> returns None (commentary disabled).
#   - SDK missing / API error -> returns None, never raises.
# The bot runs fully without it; this only adds narration on top
# of real indicators, trade levels, and calibrated probability.
#
# Uses prompt caching on the (stable) persona system prompt.
# ============================================================

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("commentary")

MODEL = os.getenv("COMMENTARY_MODEL", "claude-opus-4-8")
_MAX_TOKENS = 700

# The persona — honest version. Stable across calls so it caches.
SYSTEM_PROMPT = """You are a disciplined quantitative trading analyst writing a short \
desk note on ONE ticker. A separate engine has already computed every number you \
will see. Your job is to interpret those numbers in a sharp, professional voice — \
NOT to generate new ones.

Hard rules (these override any persona styling):
1. Use ONLY the numbers provided in the input. Never invent prices, indicator \
values, news, sentiment, order-flow, or social-media data. If something is not in \
the input, you do not know it — say so or omit it.
2. The confidence figure is a MEASURED, back-tested probability that this setup \
reaches its first target before its stop (its calibrated historical hit-rate). \
Report that number. Do NOT claim "80% confidence" or any figure the data does not \
support. If confidence is ~50%, say ~50%.
3. Always pair win-rate with expectancy/reward-risk. A high hit-rate at a tight \
target can still be a losing trade; a ~50% hit-rate at 2:1 is a real edge. Be \
explicit about this trade-off when relevant.
4. Respect the engine's signal (BUY/SELL/HOLD) and trade plan. If it says HOLD, do \
not manufacture a trade.
5. Penny / low-liquidity names: flag liquidity and pump-and-dump risk plainly.
6. End with one line: "Not financial advice — analysis of computed indicators only."

Format (keep it tight, no preamble):
### [TICKER] — [SIGNAL]
- **Read:** one-sentence synthesis of the technical picture from the data.
- **Top confluence:** the 3 strongest supporting indicators, by name + value.
- **Confidence:** the calibrated hit-rate, with the expectancy/RR caveat.
- **Plan:** entry / stop / TP1 / TP2 from the trade plan (omit if HOLD).
- **Risk:** risk level + any liquidity/penny caveat.
- **Bottom line:** one sentence."""


def _payload(result: dict) -> dict:
    """Extract the JSON-safe, deterministic fact sheet handed to the model.

    Only computed values — no free text — so there is nothing for the model to
    anchor on except real numbers.
    """
    ind = result.get("indicators", {})
    plan = result.get("trade_plan")
    return {
        "ticker": result.get("ticker"),
        "signal": result.get("signal"),
        "score_0_100": result.get("score"),
        "calibrated_confidence_pct": result.get("confidence_pct"),
        "confidence_basis": result.get("confidence_basis"),
        "confidence_is_trusted": result.get("confidence_trusted"),
        "confidence_label": result.get("confidence"),
        "regime": result.get("regime"),
        "adx": result.get("adx"),
        "risk_level": result.get("risk"),
        "is_penny": result.get("is_penny"),
        "tradable": result.get("tradable"),
        "liquidity": result.get("liquidity"),
        "liquidity_note": result.get("liquidity_note"),
        "trade_plan": plan,
        "indicators": {
            "price": ind.get("price"),
            "rsi": ind.get("rsi"),
            "mfi": ind.get("mfi"),
            "williams_r": ind.get("williams_r"),
            "macd": ind.get("macd"),
            "macd_signal": ind.get("macd_signal"),
            "macd_hist": ind.get("macd_hist"),
            "ema_9": ind.get("ema_9"),
            "ema_21": ind.get("ema_21"),
            "sma_50": ind.get("sma_50"),
            "adx": ind.get("adx"),
            "plus_di": ind.get("plus_di"),
            "minus_di": ind.get("minus_di"),
            "supertrend_dir": ind.get("supertrend_dir"),
            "above_vwap": ind.get("above_vwap"),
            "vwap_pct": ind.get("vwap_pct"),
            "bb_pct_b": ind.get("bb_pct_b"),
            "atr": ind.get("atr"),
            "volume_ratio": ind.get("volume_ratio"),
            "volume_spike": ind.get("volume_spike"),
            "obv_slope": ind.get("obv_slope"),
            "patterns": ind.get("patterns"),
        },
        "engine_reasons": result.get("reasons", [])[:8],
    }


def is_enabled() -> bool:
    """True only if a key is present AND the SDK imports."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except Exception:
        return False
    return True


def generate(result: dict) -> str | None:
    """Return persona commentary for one signal, or None if disabled/failed.

    Never raises — any problem yields None so the scan loop is unaffected.
    """
    if not is_enabled():
        return None
    try:
        import anthropic

        client = anthropic.Anthropic()
        facts = json.dumps(_payload(result), sort_keys=True, indent=2)
        msg = client.messages.create(
            model=MODEL,
            max_tokens=_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # stable persona → cache it
            }],
            messages=[{
                "role": "user",
                "content": (
                    "Write the desk note for this signal. Use only these computed "
                    f"values:\n\n```json\n{facts}\n```"
                ),
            }],
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip() or None
    except Exception as e:
        log.warning("commentary generation failed: %s", e)
        return None


if __name__ == "__main__":
    # Smoke test against a live scan: python commentary.py AAPL
    import sys
    import scanner

    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    if not is_enabled():
        print("Commentary disabled — set ANTHROPIC_API_KEY and `pip install anthropic`.")
        print("Fact sheet that WOULD be sent (no API call):\n")
        r = scanner.scan_ticker(ticker)
        print(json.dumps(_payload(r), indent=2) if r else f"No data for {ticker}")
        sys.exit(0)
    r = scanner.scan_ticker(ticker)
    if not r:
        print(f"No data for {ticker}")
        sys.exit(1)
    note = generate(r)
    print(note or "(commentary unavailable)")
