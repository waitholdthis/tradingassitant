# Confidence Calibration — and the honest answer to "80% confidence"

The original brief asked for an **80% confidence** signal. This document explains
how confidence is now *measured* (not asserted), what the data actually says, and
why "80% confidence" is the wrong target to optimize for.

## How confidence is computed

`calibration.py` runs a **walk-forward backtest of the real signal engine**:

1. For each symbol, step through history bar by bar (no look-ahead).
2. At each bar, run the actual `signals.generate_signal()` on the data up to that bar.
3. For every BUY/SELL it emits, simulate the trade plan: enter at the next bar's
   open, then check whether price reaches the **first target (TP1)** before the
   **stop**, within a holding window.
4. Bucket the outcomes by signal score and compute the win rate with a
   **Wilson lower bound** — so a bucket can only claim 80% if it *measurably* hit
   80% with enough samples to trust it.

The live engine then reports that measured number as `confidence_pct`. A signal is
labelled high-confidence only when the historical data earns it.

Regenerate any time:

```bash
python calibration.py                       # default basket, 2y daily, TP1=1R
python calibration.py --target-rr 0.25      # test a tighter target
python calibration.py --symbols AAPL,TSLA   # custom basket
```

## What the data says (3,100+ simulated trades, 20-symbol basket, 2y daily)

**BUY signals, win rate vs. how far the target sits (stop = 1R):**

| Target | Win rate | Confidence (Wilson) | Expectancy / trade |
|--------|----------|---------------------|--------------------|
| 0.25R  | ~79%     | **~78%**            | **≈ −0.01R** (break-even / negative) |
| 0.50R  | ~67%     | ~65%                | ≈ 0.00R |
| 1.00R  | ~54%     | ~52%                | +0.08R |
| 1.50R  | ~50%     | ~48%                | +0.25R |
| 2.00R  | ~49%     | ~48%                | **+0.48R** (best) |

## The honest conclusion

**80% confidence is reachable — but it is the wrong objective.**

- You can hit a ~78–80% win rate, but only by setting a tight ~0.25R target
  (about half an ATR). At that distance the trade has **roughly zero or negative
  expectancy**: the occasional full-stop loss (−1R) cancels all the small wins.
- The engine's actual **edge lives at the 2R target** — only ~49% win rate, but
  **+0.48R per trade**. At 2:1 reward:risk, breakeven is a 33% win rate, so ~49% is
  a genuine, strong positive expectancy.
- **High win-rate ≠ profitable.** Anyone selling an "80% win-rate" penny-stock
  signal is selling the tight-target illusion. This system refuses to do that: it
  reports the measured hit-rate *and* the expectancy, so the trade-off is never
  hidden.

## What this means for the product

- The trade plan ships **two targets**: `TP1` (1R, the calibrated number) and
  `TP2` (2R, the runner where the expectancy is). Take partial at TP1, let the rest
  run to TP2.
- The live `confidence_pct` is the calibrated hit-rate of TP1 — typically ~50% for
  this engine on these names. That is the truth, and it is still a profitable edge
  at 2:1.
- The SELL/short side calibrated to **negative expectancy** on this basket — the
  engine has no demonstrated short edge here. Treat SELL signals as exits, not as
  shorts, until that changes.

> Calibration is a prior, not a guarantee. It was fit on daily bars across a fixed
> basket; live trading is intraday on different names. Recalibrate on your own
> universe/timeframe before sizing real risk. Not financial advice.
