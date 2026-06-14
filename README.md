# 📈 Trading Signal Bot + Trading Assistant

A live market scanner that generates **BUY / SELL / HOLD** signals from 14+
indicators and **pushes actionable alerts straight to your phone** — combined
with a zero-dependency research toolkit (`trading_assistant/`) for
backtesting, risk sizing, and portfolio tracking. Signals only — you execute
trades.

> **Disclaimer:** technical analysis only. **Not financial advice.** All
> trading decisions are your responsibility. Past signal accuracy does not
> guarantee future results.

## Quick start

```bash
pip install -r requirements.txt

# Web dashboard  ← recommended
python app.py            # open http://localhost:5000

# Terminal scanner (pushes mobile alerts when configured)
python main.py           # continuous scan loop
python main.py --once    # one-time scan
python main.py --ticker TSLA   # deep-scan single stock
python main.py --notify-test   # send a test push to your phone
```

## 📱 Mobile push alerts

Actionable BUY/SELL signals are pushed to your phone with the score, the top
reasons, and a complete trade plan (entry, ATR-based stop-loss, take-profit,
and position size for your account). Three channels are supported — enable any
or all in `config.py` / environment variables:

### ntfy (fastest setup — no account needed)

1. Install the **ntfy** app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/us/app/ntfy/id1625396347))
2. In the app, subscribe to a topic with a hard-to-guess name, e.g. `my-trades-x7k2p9`
3. Configure the bot:

```bash
export NTFY_TOPIC="my-trades-x7k2p9"
python main.py
```

That's it — alerts now arrive on your phone. (Anyone who knows the topic name
can see the alerts, so treat it like a password.)

### Pushover

```bash
export PUSHOVER_TOKEN="your-app-token"
export PUSHOVER_USER="your-user-key"
```

### Telegram

Create a bot with [@BotFather](https://t.me/BotFather), get your chat id from
[@userinfobot](https://t.me/userinfobot), then:

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="123456789"
```

STRONG signals are sent at high priority (bypasses quiet hours on ntfy and
Pushover). A per-ticker cooldown (`ALERT_COOLDOWN_MINUTES`) prevents repeat
notifications, including from dashboard auto-refresh.

## Web dashboard

Open **http://localhost:5000** after running `python app.py`.

| Feature | How |
|---|---|
| Scan all watchlist stocks | Click **Scan All** |
| Scan a single stock | Type ticker → **Deep Scan** |
| Add / remove watchlist stock | Type ticker → **+ Add**, or × on a chip |
| Full signal breakdown | Click any signal card |
| Auto-refresh every 60s | Check **Auto-refresh** |

Scans triggered from the dashboard push mobile alerts too.

## Signal scoring (0–100)

| Score | Signal | Meaning |
|---|---|---|
| 80–100 | **BUY** STRONG | Multiple strong indicators aligned |
| 65–79 | **BUY** MODERATE | Clear bullish setup |
| 36–64 | **HOLD** | No clear edge — wait |
| 21–35 | **SELL** MODERATE | Clear bearish setup |
| 0–20 | **SELL** STRONG | Multiple strong indicators bearish |

**Indicators:** Supertrend · EMA 9/21 · SMA 50/200 · MACD · RSI · MFI ·
Williams %R · Stochastic · OBV · VWAP · volume ratio · Bollinger Bands · ATR ·
ADX regime filter · candlestick patterns (hammer, engulfing, marubozu, doji,
three soldiers/crows)

**Confluence gate:** BUY/SELL requires **3+ independent confirming
indicators**; ranging markets (ADX < 20) are dampened.

## Calibrated confidence (the honest "% confidence")

The 0–100 score is also mapped to a **measured probability** — the historical
hit-rate of that score bucket, computed by a walk-forward backtest of the real
engine (`calibration.py`), reported as a **Wilson lower bound** so small samples
can't over-claim. Every signal carries `confidence_pct` = the calibrated chance
it reaches its first target (TP1) before its stop.

```bash
python calibration.py            # build/refresh calibration.json (2y daily basket)
python calibration.py --target-rr 0.25   # see how a tighter target changes the win rate
```

**This is the real answer to "give me 80% confidence":** 80% is reachable only
with a very tight (~0.25R) target whose expectancy is ≈ 0 — the frequent small
wins are cancelled by the occasional full stop. The engine's actual edge is at
the **2R target** (~50% win rate, **+0.48R/trade**). High win-rate ≠ profit.
Full analysis and numbers in **[CALIBRATION.md](CALIBRATION.md)**.

## Liquidity guard (anti pump-and-dump)

Every signal is checked for genuine tradability before it can alert: a price
floor, a **minimum average daily dollar-volume** (the real exit-liquidity test),
a share-volume floor, and a wide-bar/thin-book proxy. Illiquid traps are marked
`tradable: false` and never pushed. Tune in `config.py` (`MIN_AVG_DAILY_DOLLAR_VOL`
etc.). A dedicated liquid-penny-mover screen is in `scanner.screen_penny_movers()`.

## Options suggestions (calls & puts with price targets)

A BUY maps to a **CALL**, a SELL to a **PUT**. `options.py` pulls the live chain
(yfinance), picks a liquid contract near a target delta (~ATM) and ~30 DTE, then
**prices it with Black-Scholes** to produce concrete option dollar targets:

```bash
python options.py AAPL              # CLI
python main.py --ticker AAPL        # deep-scan now includes the options play
# or click "Suggest call/put + price targets" in the dashboard detail panel
# or POST /api/options/<ticker>
```

Output example:

```
CALL · AAPL 295 2026-07-10 (27DTE, OTM, Δ+0.45, IV 24%)
  BUY  ≤ $5.85  (bid $5.50 / ask $5.85; $585/contract max risk)
  SELL TP1 $9.73 (+66%) · TP2 $15.50 (+165%)
  STOP $2.55   ·   breakeven underlying $300.85
```

**Two honest design choices, both deliberate:**

1. **Targets are scaled to the option's horizon, not the 5-minute scalp.** The
   stock plan's intraday ATR (~0.3% moves) is far too small to beat option theta
   and spread over a multi-day hold — mapping it straight across gives *negative*
   option returns. Instead the underlying targets are sized to a ~1σ **implied
   move** over the hold (`σ = spot·IV·√(hold/365)`): TP1 = +1σ, TP2 = +2σ,
   stop = −1σ.
2. **The calibrated % is the underlying's hit-rate, not the option's P&L.**
   Options add IV-crush and theta the stock backtest doesn't model, so option
   prices are Black-Scholes estimates at constant IV, and liquidity (bid/ask
   spread, open interest) is gated. Verify the live quote before trading.

Tune in `config.py`: `OPTIONS_TARGET_DTE`, `OPTIONS_TARGET_DELTA`,
`OPTIONS_HOLD_DAYS`, `OPTIONS_MAX_SPREAD_PCT`, `OPTIONS_MIN_OPEN_INT`.

## AI desk note (optional)

`commentary.py` adds an optional LLM-written analyst note, fed **only** the
computed indicators, trade plan, and *calibrated* confidence — it is told not to
invent data or claim an unearned confidence figure. Off by default; enable with:

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
python commentary.py AAPL        # CLI, or click "Generate desk note" in the dashboard
```

## Reliability

The scan loop is built to run unattended:

- Data fetches retry with exponential backoff before giving up on a ticker
- One bad ticker never aborts a scan; one bad scan never kills the loop
- Push notification failures are logged and retried, never fatal
- Per-ticker/per-direction alert cooldown stops notification storms

## Configuration (`config.py`)

| Setting | Default | Description |
|---|---|---|
| `WATCHLIST` | 12 tickers | Stocks to monitor |
| `SCAN_INTERVAL_SECONDS` | 60 | Seconds between auto scans |
| `RSI_OVERSOLD` / `RSI_OVERBOUGHT` | 30 / 70 | RSI thresholds |
| `VOLUME_SPIKE_MULT` | 2.0 | Volume multiplier = spike |
| `MIN_SIGNAL_SCORE` | 60 | Minimum score to alert |
| `ALERT_COOLDOWN_MINUTES` | 10 | Re-alert suppression window |
| `ACCOUNT_EQUITY` | 10000 | Used to size positions in trade plans |
| `RISK_PER_TRADE` | 0.01 | Fraction of equity risked per trade |
| `NTFY_TOPIC` etc. | env vars | Push channel credentials |

## Research toolkit (`trading_assistant/`)

A standard-library-only package for offline research, fully unit-tested. It
also powers the trade plan (stop/target/position size) attached to every push
alert.

```bash
# Technical snapshot, strategy backtests, position sizing
python -m trading_assistant analyze --fetch AAPL --period 1y
python -m trading_assistant backtest --demo --strategy ensemble
python -m trading_assistant compare --demo
python -m trading_assistant size --equity 50000 --price 185.50 --atr 3.2
```

- **Strategies** — SMA crossover, RSI mean reversion, MACD momentum, Bollinger
  breakout, Donchian breakout, majority-vote ensemble
- **Backtester** — fills at next bar's open (no look-ahead), commission +
  slippage, CAGR/Sharpe/Sortino/max-drawdown/profit-factor metrics
- **Risk** — fixed-fractional and ATR position sizing, capped Kelly, brackets,
  trailing stops
- **Portfolio** — positions, P&L, allocation weights, JSON persistence

Library use:

```python
from trading_assistant import Backtester, SmaCrossover
from trading_assistant.data import fetch_yfinance

series = fetch_yfinance("AAPL", period="2y")
result = Backtester(initial_capital=100_000).run(SmaCrossover(20, 50), series)
print(result.summary())
```

## Tests

```bash
python -m pytest          # unit tests (offline, no network needed)
python backtest.py        # scenario validation of the live signal engine
```
