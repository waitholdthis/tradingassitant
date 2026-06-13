# 📈 Trading Signal Bot

Real-time market scanner that generates **BUY / SELL / HOLD** signals using 14+ professional-grade indicators. Signals only — you execute trades.

## Quick Start

```bash
cd trading_bot

# 1. Install dependencies
pip install -r requirements.txt

# 2. Launch the web dashboard  ← recommended
python app.py
# Then open http://localhost:5000 in your browser

# 3. OR run in the terminal
python main.py          # continuous scan loop
python main.py --once   # one-time scan
python main.py --ticker TSLA  # deep-scan single stock
```

## Web Dashboard

Open **http://localhost:5000** after running `python app.py`.

| Feature | How |
|---|---|
| Scan all watchlist stocks | Click **Scan All** |
| Scan a single stock | Type ticker → **Deep Scan** |
| Add stock to watchlist | Type ticker → **+ Add** |
| Remove from watchlist | Click × on any chip |
| See full signal breakdown | Click any signal card |
| Re-scan a stock from detail view | **↻ Re-scan** button |
| Auto-refresh every 60s | Check **Auto-refresh** |

## Signal Scoring (0–100)

| Score | Signal | Meaning |
|---|---|---|
| 80–100 | **BUY** STRONG | Multiple strong indicators aligned |
| 65–79 | **BUY** MODERATE | Clear bullish setup |
| 36–64 | **HOLD** | No clear edge — wait |
| 21–35 | **SELL** MODERATE | Clear bearish setup |
| 0–20 | **SELL** STRONG | Multiple strong indicators bearish |

## Indicators (14+)

**Trend:** Supertrend · EMA 9/21 · SMA 50/200 · MACD  
**Momentum:** RSI · MFI · Williams %R · Stochastic  
**Volume:** OBV · VWAP · Volume ratio  
**Volatility:** Bollinger Bands · ATR  
**Regime:** ADX (trend strength filter)  
**Patterns:** Hammer · Engulfing · Marubozu · Doji · Three Soldiers/Crows

## Confluence Gate

Signals require **3+ independent confirming indicators** to fire as BUY/SELL.  
Ranging markets (ADX < 20) are automatically dampened.

## Configuration (`config.py`)

| Setting | Default | Description |
|---|---|---|
| `WATCHLIST` | 12 tickers | Stocks to monitor |
| `SCAN_INTERVAL_SECONDS` | 60 | Seconds between auto scans |
| `RSI_OVERSOLD` | 30 | RSI threshold for oversold |
| `RSI_OVERBOUGHT` | 70 | RSI threshold for overbought |
| `VOLUME_SPIKE_MULT` | 2.0 | Volume multiplier = spike |
| `PENNY_STOCK_MAX_PRICE` | $5.00 | Penny stock threshold |

## ⚠ Disclaimer

Signals are based on technical analysis only. **Not financial advice.** All trading decisions and order executions are your responsibility. Past signal accuracy does not guarantee future results.
