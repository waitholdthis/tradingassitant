# ============================================================
# TECHNICAL INDICATORS ENGINE  (v2 - Professional Grade)
# RSI, MACD, Bollinger Bands, EMA/SMA, Stochastic, ATR
# + ADX, Supertrend, OBV, MFI, VWAP, Williams %R
# + Candlestick pattern detection
# ============================================================
import numpy as np
import pandas as pd


# ── CORE INDICATORS ───────────────────────────────────────────

def compute_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = float(rsi.iloc[-1]) if not rsi.empty else 50.0
    if np.isnan(val):
        lg = float(avg_gain.iloc[-1]) if not avg_gain.empty else 0
        ll = float(avg_loss.iloc[-1]) if not avg_loss.empty else 0
        val = 100.0 if (ll == 0 and lg > 0) else (50.0 if ll == 0 else 0.0)
    return round(val, 2)


def compute_macd(close, fast=12, slow=26, signal=9):
    ef = close.ewm(span=fast, adjust=False).mean()
    es = close.ewm(span=slow, adjust=False).mean()
    ml = ef - es
    sl = ml.ewm(span=signal, adjust=False).mean()
    return round(float(ml.iloc[-1]), 4), round(float(sl.iloc[-1]), 4), round(float((ml - sl).iloc[-1]), 4)


def compute_bollinger(close, period=20, std_dev=2.0):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    bw = upper.iloc[-1] - lower.iloc[-1]
    pct_b = (close.iloc[-1] - lower.iloc[-1]) / bw if bw != 0 else 0.5
    return {"upper": round(float(upper.iloc[-1]), 4), "mid": round(float(sma.iloc[-1]), 4),
            "lower": round(float(lower.iloc[-1]), 4), "pct_b": round(float(pct_b), 4)}


def compute_ema(close, period):
    return round(float(close.ewm(span=period, adjust=False).mean().iloc[-1]), 4)


def compute_sma(close, period):
    if len(close) < period:
        return round(float(close.mean()), 4)
    return round(float(close.rolling(period).mean().iloc[-1]), 4)


def compute_volume_analysis(volume):
    avg = float(volume.iloc[:-1].mean())
    cur = float(volume.iloc[-1])
    ratio = cur / avg if avg > 0 else 1.0
    return {"current": int(cur), "average": int(avg), "ratio": round(ratio, 2), "is_spike": ratio >= 2.0}


def compute_stochastic(high, low, close, k_period=14, d_period=3):
    ll = low.rolling(k_period).min()
    hh = high.rolling(k_period).max()
    denom = (hh - ll).replace(0, np.nan)
    k = 100 * (close - ll) / denom
    d = k.rolling(d_period).mean()
    return round(float(k.iloc[-1]), 2), round(float(d.iloc[-1]), 2)


def compute_atr(high, low, close, period=14):
    pc = close.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return round(float(tr.ewm(com=period - 1, min_periods=period).mean().iloc[-1]), 4)


# ── PROFESSIONAL INDICATORS ───────────────────────────────────

def compute_adx(high, low, close, period=14):
    """
    Average Directional Index (ADX) + DI lines.
    ADX measures trend STRENGTH regardless of direction:
      < 20 = no trend / ranging market (avoid trading)
      20-25 = weak trend (proceed with caution)
      25-40 = strong trend (good trading conditions)
      > 40 = very strong trend (momentum trade)
    Returns: adx, plus_di, minus_di
    """
    pc = close.shift(1)
    ph = high.shift(1)
    pl = low.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    plus_dm  = ((high - ph).clip(lower=0)).where((high - ph) > (pl - low), 0)
    minus_dm = ((pl - low).clip(lower=0)).where((pl - low) > (high - ph), 0)
    atr_s    = tr.ewm(com=period - 1, min_periods=period).mean()
    plus_di  = 100 * plus_dm.ewm(com=period - 1, min_periods=period).mean() / atr_s.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(com=period - 1, min_periods=period).mean() / atr_s.replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(com=period - 1, min_periods=period).mean()
    return (round(float(adx.iloc[-1]), 2),
            round(float(plus_di.iloc[-1]), 2),
            round(float(minus_di.iloc[-1]), 2))


def compute_supertrend(high, low, close, period=10, multiplier=3.0):
    """
    Supertrend: dynamic support/resistance that flips with trend.
    Returns: (direction, supertrend_level)
      direction = 1 (price above = bullish), -1 (price below = bearish)
    One of the most reliable trend-following indicators available.
    """
    atr_s = compute_atr(high, low, close, period)
    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr_s
    lower_band = hl2 - multiplier * atr_s
    supertrend = pd.Series(index=close.index, dtype=float)
    direction  = pd.Series(index=close.index, dtype=float)
    for i in range(len(close)):
        if i == 0:
            supertrend.iloc[i] = upper_band.iloc[i]
            direction.iloc[i] = -1
            continue
        prev_st  = supertrend.iloc[i - 1]
        prev_dir = direction.iloc[i - 1]
        curr_ub  = float(upper_band.iloc[i])
        curr_lb  = float(lower_band.iloc[i])
        if prev_dir == 1:
            curr_st = max(curr_lb, prev_st) if float(close.iloc[i]) > prev_st else curr_ub
            curr_dir = 1 if float(close.iloc[i]) > curr_st else -1
        else:
            curr_st = min(curr_ub, prev_st) if float(close.iloc[i]) < prev_st else curr_lb
            curr_dir = -1 if float(close.iloc[i]) < curr_st else 1
        supertrend.iloc[i] = curr_st
        direction.iloc[i] = curr_dir
    return int(direction.iloc[-1]), round(float(supertrend.iloc[-1]), 4)


def compute_obv(close, volume):
    """
    On-Balance Volume: cumulative volume that tracks buying/selling pressure.
    Rising OBV with rising price = healthy uptrend (confirmed).
    Rising OBV with falling price = bullish divergence (reversal signal).
    """
    obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    obv_ema = obv.ewm(span=20, adjust=False).mean()
    obv_slope = float(obv.iloc[-1]) - float(obv.iloc[-5]) if len(obv) >= 5 else 0
    return {
        "obv":       round(float(obv.iloc[-1]), 0),
        "obv_ema":   round(float(obv_ema.iloc[-1]), 0),
        "obv_above": float(obv.iloc[-1]) > float(obv_ema.iloc[-1]),  # bullish when above EMA
        "obv_slope": round(obv_slope, 0),   # positive = accumulating, negative = distributing
    }


def compute_mfi(high, low, close, volume, period=14):
    """
    Money Flow Index: volume-weighted RSI (0-100).
    Combines price AND volume — harder to fake than RSI alone.
    < 20 = oversold (BUY),  > 80 = overbought (SELL)
    """
    typical = (high + low + close) / 3
    raw_mf  = typical * volume
    delta   = typical.diff()
    pos_mf  = raw_mf.where(delta > 0, 0).rolling(period).sum()
    neg_mf  = raw_mf.where(delta < 0, 0).rolling(period).sum()
    mfr     = pos_mf / neg_mf.replace(0, np.nan)
    mfi     = 100 - (100 / (1 + mfr))
    val     = float(mfi.iloc[-1]) if not mfi.empty else 50.0
    return round(val if not np.isnan(val) else 50.0, 2)


def compute_vwap(high, low, close, volume):
    """
    VWAP: Volume Weighted Average Price — institutional benchmark.
    Price above VWAP = bullish bias (buyers in control).
    Price below VWAP = bearish bias (sellers in control).
    """
    typical = (high + low + close) / 3
    vwap    = (typical * volume).cumsum() / volume.cumsum()
    price   = float(close.iloc[-1])
    vwap_v  = float(vwap.iloc[-1])
    pct_from = (price - vwap_v) / vwap_v * 100 if vwap_v != 0 else 0
    return {
        "vwap":     round(vwap_v, 4),
        "above":    price > vwap_v,
        "pct_from": round(pct_from, 2),
    }


def compute_williams_r(high, low, close, period=14):
    """
    Williams %R: momentum oscillator (-100 to 0).
    > -20 = overbought,  < -80 = oversold.
    Faster than RSI — good for early reversal detection.
    """
    hh = high.rolling(period).max()
    ll = low.rolling(period).min()
    denom = (hh - ll).replace(0, np.nan)
    wr = -100 * (hh - close) / denom
    val = float(wr.iloc[-1]) if not wr.empty else -50.0
    return round(val if not np.isnan(val) else -50.0, 2)


# ── CANDLESTICK PATTERNS ──────────────────────────────────────

def detect_patterns(open_, high, low, close):
    """
    Detect key candlestick reversal and continuation patterns.
    Returns dict of detected patterns with bullish/bearish classification.
    """
    o, h, l, c = open_.iloc[-1], high.iloc[-1], low.iloc[-1], close.iloc[-1]
    po, ph, pl, pc = open_.iloc[-2], high.iloc[-2], low.iloc[-2], close.iloc[-2]
    body      = abs(c - o)
    full_range = h - l if (h - l) > 0 else 0.0001
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    patterns = {}

    # Doji: body < 10% of range → indecision
    if body / full_range < 0.10:
        patterns["doji"] = "neutral"

    # Hammer (bullish): long lower wick (2× body), small upper wick, at bottom
    if lower_wick >= 2 * body and upper_wick <= body * 0.3:
        patterns["hammer"] = "bullish"

    # Shooting Star (bearish): long upper wick, small lower wick
    if upper_wick >= 2 * body and lower_wick <= body * 0.3:
        patterns["shooting_star"] = "bearish"

    # Bullish Engulfing: prev red candle, current green candle engulfs it
    if pc < po and c > o and c > po and o < pc:
        patterns["bullish_engulfing"] = "bullish"

    # Bearish Engulfing: prev green candle, current red engulfs it
    if pc > po and c < o and c < po and o > pc:
        patterns["bearish_engulfing"] = "bearish"

    # Marubozu (strong momentum): body > 90% of range
    if body / full_range > 0.90:
        patterns["marubozu"] = "bullish" if c > o else "bearish"

    # Three-bar pattern: check prior 3 bars
    if len(close) >= 4:
        c1, c2, c3 = close.iloc[-4], close.iloc[-3], close.iloc[-2]
        o1, o2, o3 = open_.iloc[-4], open_.iloc[-3], open_.iloc[-2]
        # Three white soldiers: 3 consecutive bullish closes
        if c1 > o1 and c2 > o2 and c3 > o3 and c3 > c2 > c1:
            patterns["three_white_soldiers"] = "bullish"
        # Three black crows: 3 consecutive bearish closes
        if c1 < o1 and c2 < o2 and c3 < o3 and c3 < c2 < c1:
            patterns["three_black_crows"] = "bearish"

    return patterns


# ── MASTER RUN_ALL ────────────────────────────────────────────

def run_all(df):
    """Run all indicators. Returns unified dict."""
    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df["Volume"]
    open_  = df["Open"]

    ml, ms, mh = compute_macd(close)
    bb  = compute_bollinger(close)
    vol = compute_volume_analysis(volume)
    sk, sd = compute_stochastic(high, low, close)
    adx_v, plus_di, minus_di = compute_adx(high, low, close)
    st_dir, st_level = compute_supertrend(high, low, close)
    obv_d  = compute_obv(close, volume)
    vwap_d = compute_vwap(high, low, close, volume)
    patterns = detect_patterns(open_, high, low, close)

    return {
        # Price
        "price":        round(float(close.iloc[-1]), 4),
        "price_open":   round(float(open_.iloc[-1]), 4),
        "price_high":   round(float(high.iloc[-1]), 4),
        "price_low":    round(float(low.iloc[-1]), 4),
        # Momentum oscillators
        "rsi":          compute_rsi(close),
        "mfi":          compute_mfi(high, low, close, volume),
        "williams_r":   compute_williams_r(high, low, close),
        "stoch_k":      sk,
        "stoch_d":      sd,
        # Trend
        "macd":         ml,
        "macd_signal":  ms,
        "macd_hist":    mh,
        "ema_9":        compute_ema(close, 9),
        "ema_21":       compute_ema(close, 21),
        "sma_50":       compute_sma(close, 50),
        "sma_200":      compute_sma(close, 200),
        # Trend strength
        "adx":          adx_v,
        "plus_di":      plus_di,
        "minus_di":     minus_di,
        "adx_trending": adx_v >= 25,   # True = real trend, filter out noise
        # Supertrend
        "supertrend_dir":   st_dir,    # 1=bullish, -1=bearish
        "supertrend_level": st_level,
        # Volatility / Bands
        "bb_upper":     bb["upper"],
        "bb_mid":       bb["mid"],
        "bb_lower":     bb["lower"],
        "bb_pct_b":     bb["pct_b"],
        "atr":          compute_atr(high, low, close),
        # Volume
        "volume":       vol["current"],
        "volume_avg":   vol["average"],
        "volume_ratio": vol["ratio"],
        "volume_spike": vol["is_spike"],
        # OBV
        "obv":          obv_d["obv"],
        "obv_above_ema":obv_d["obv_above"],
        "obv_slope":    obv_d["obv_slope"],
        # VWAP
        "vwap":         vwap_d["vwap"],
        "above_vwap":   vwap_d["above"],
        "vwap_pct":     vwap_d["pct_from"],
        # Candlestick patterns
        "patterns":     patterns,
    }
