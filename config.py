# ============================================================
# TRADING BOT CONFIGURATION
# Edit this file to customize your watchlist and thresholds
# ============================================================

# ── WATCHLIST ────────────────────────────────────────────────
# Add any ticker symbols you want to monitor
WATCHLIST = [
    # Penny stocks (under $5)
    "SNDL", "MARA", "CLOV", "BBIG", "ATER",
    # Mid-cap momentum plays
    "AMC", "GME", "BBBY",
    # Large-cap anchors (for signal calibration)
    "AAPL", "TSLA", "NVDA", "SPY",
]

# ── SCAN SETTINGS ────────────────────────────────────────────
SCAN_INTERVAL_SECONDS = 60       # How often to rescan (seconds)
LOOKBACK_PERIOD = "5d"           # Historical data window: 1d, 5d, 1mo, 3mo
INTRADAY_INTERVAL = "5m"         # Candle size: 1m, 2m, 5m, 15m, 30m, 60m

# ── SIGNAL THRESHOLDS ────────────────────────────────────────
RSI_OVERSOLD      = 30           # RSI below this → potential BUY
RSI_OVERBOUGHT    = 70           # RSI above this → potential SELL
VOLUME_SPIKE_MULT = 2.0          # Volume X times avg → confirms signal
MIN_SIGNAL_SCORE  = 60           # Minimum score (0-100) to emit alert

# ── PENNY STOCK FILTER ───────────────────────────────────────
PENNY_STOCK_MAX_PRICE = 5.00     # Tickers at or below this are "penny stocks"
FOCUS_PENNY_STOCKS    = False    # If True, only alert on penny stocks

# ── ALERT SETTINGS ───────────────────────────────────────────
LOG_FILE = "alerts.log"          # File to save all alerts
ALERT_COOLDOWN_MINUTES = 10      # Don't re-alert same ticker for N minutes

# ── DISPLAY ──────────────────────────────────────────────────
SHOW_ALL_TICKERS = True          # Show HOLD signals too (not just BUY/SELL)
CLEAR_SCREEN      = True         # Clear terminal between scans
