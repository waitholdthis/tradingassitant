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

# ── LIQUIDITY GUARD (anti pump-and-dump / liquidity trap) ────
# A signal must clear these to be actionable. The dollar-volume floor is the
# single most important defense against illiquid traps: a name can spike 300%
# on a press release, but if it normally trades $50k/day you cannot exit a real
# position without crushing the price. Require genuine, sustained liquidity.
MIN_PRICE              = 0.50     # reject sub-$0.50 junk / near-delisted shells
MIN_AVG_DAILY_DOLLAR_VOL = 1_000_000   # >= $1M average daily $-volume to trade
MIN_AVG_DAILY_VOLUME   = 300_000  # >= 300k average daily shares
MAX_SPREAD_PROXY_PCT   = 8.0      # reject if one bar's range > this % of price
                                  # (wide bars ≈ thin book ≈ slippage on exit)
ENFORCE_LIQUIDITY      = True     # set False to disable the guard entirely

# ── ALERT SETTINGS ───────────────────────────────────────────
LOG_FILE = "alerts.log"          # File to save all alerts
ALERT_COOLDOWN_MINUTES = 10      # Don't re-alert same ticker for N minutes

# ── DISPLAY ──────────────────────────────────────────────────
SHOW_ALL_TICKERS = True          # Show HOLD signals too (not just BUY/SELL)
CLEAR_SCREEN      = True         # Clear terminal between scans

# ── MOBILE PUSH NOTIFICATIONS ────────────────────────────────
# Configure any (or all) channels via environment variables.
# See README "Mobile push alerts" for setup instructions.
import os

# ntfy.sh — easiest: install the ntfy app, subscribe to your topic
NTFY_TOPIC  = os.getenv("NTFY_TOPIC", "")          # e.g. "my-trades-x7k2p9"
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")

# Pushover
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN", "")
PUSHOVER_USER  = os.getenv("PUSHOVER_USER", "")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ── UNIVERSE SCAN ─────────────────────────────────────────────
# Scans every US-listed stock (~9,000 tickers) to find the top 10 BUYs.
UNIVERSE_SCAN_WORKERS   = int(os.getenv("UNIVERSE_SCAN_WORKERS", "20"))  # parallel threads
UNIVERSE_SCAN_TIME_ET   = os.getenv("UNIVERSE_SCAN_TIME_ET", "09:00")    # daily trigger in ET (e.g. "09:00")

# ── TRADE PLAN SIZING (attached to every push alert) ─────────
ACCOUNT_EQUITY = float(os.getenv("ACCOUNT_EQUITY", "10000"))  # your account size ($)
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.01"))   # fraction of equity risked per trade

# ── OPTIONS SUGGESTIONS (calls / puts with price targets) ────
# A BUY signal maps to a CALL, a SELL signal to a PUT. The contract is chosen
# near a target delta and days-to-expiry, then Black-Scholes reprices it at the
# underlying's stop/TP1/TP2 to produce concrete buy/sell price targets.
OPTIONS_ENABLED        = True
OPTIONS_TARGET_DTE     = int(os.getenv("OPTIONS_TARGET_DTE", "30"))   # preferred days to expiry
OPTIONS_MIN_DTE        = int(os.getenv("OPTIONS_MIN_DTE", "7"))       # avoid 0DTE gamma roulette
OPTIONS_MAX_DTE        = int(os.getenv("OPTIONS_MAX_DTE", "75"))
OPTIONS_TARGET_DELTA   = float(os.getenv("OPTIONS_TARGET_DELTA", "0.50"))  # ~ATM; 0.30 = cheaper OTM
OPTIONS_HOLD_DAYS      = float(os.getenv("OPTIONS_HOLD_DAYS", "5"))   # expected hold (for theta on targets)
OPTIONS_MAX_SPREAD_PCT = float(os.getenv("OPTIONS_MAX_SPREAD_PCT", "18"))  # reject wide bid/ask
OPTIONS_MIN_OPEN_INT   = int(os.getenv("OPTIONS_MIN_OPEN_INT", "50"))      # liquidity floor
RISK_FREE_RATE         = float(os.getenv("RISK_FREE_RATE", "0.04"))
