#!/usr/bin/env python3
"""
Trading Signal Bot — Web Dashboard
Run:  python app.py
Open: http://localhost:5000
"""

import os, sys, json, time, threading
from datetime import datetime
from flask import Flask, jsonify, request, render_template_string

sys.path.insert(0, ".")
import config
import indicators
import notify
import commentary
import signals as sig_engine
import scanner as sc

app = Flask(__name__)

# ── In-memory state ──────────────────────────────────────────────
_state = {
    "watchlist":     list(config.WATCHLIST),
    "last_results":  [],
    "last_scan_ts":  None,
    "scanning":      False,
}
_lock = threading.Lock()

# ── API helpers ──────────────────────────────────────────────────

def _result_to_dict(r):
    """Serialize a scan result to JSON-safe dict."""
    if r is None:
        return None
    ind = r.get("indicators", {})
    # strip the full indicator blob — keep only what the UI needs
    return {
        "ticker":     r["ticker"],
        "signal":     r["signal"],
        "score":      r["score"],
        "confidence": r["confidence"],
        "confidence_pct":     r.get("confidence_pct"),
        "confidence_basis":   r.get("confidence_basis", "uncalibrated"),
        "confidence_trusted": r.get("confidence_trusted", False),
        "trade_plan": r.get("trade_plan"),
        "tradable":   r.get("tradable", True),
        "liquidity":  r.get("liquidity", {}),
        "liquidity_note": r.get("liquidity_note", ""),
        "risk":       r["risk"],
        "is_penny":   r["is_penny"],
        "regime":     r.get("regime", "—"),
        "adx":        round(r.get("adx", 0), 1),
        "confluence": r.get("confluence", {}),
        "reasons":    r.get("reasons", []),
        "price":      round(ind.get("price", 0), 4),
        "rsi":        round(ind.get("rsi", 0), 1),
        "macd_hist":  round(ind.get("macd_hist", 0), 4),
        "volume_ratio": round(ind.get("volume_ratio", 0), 2),
        "volume_spike": ind.get("volume_spike", False),
        "supertrend": ind.get("supertrend_dir", 0),
        "above_vwap": ind.get("above_vwap", False),
        "obv_slope":  ind.get("obv_slope", 0),
        "mfi":        round(ind.get("mfi", 50), 1),
        "williams_r": round(ind.get("williams_r", -50), 1),
        "patterns":   ind.get("patterns", {}),
        "ema_9":      round(ind.get("ema_9", 0), 4),
        "ema_21":     round(ind.get("ema_21", 0), 4),
        "bb_pct_b":   round(ind.get("bb_pct_b", 0.5), 3),
        "atr":        round(ind.get("atr", 0), 4),
        "error":      r.get("error"),
        "ts":         datetime.now().strftime("%H:%M:%S"),
    }


def _scan_ticker_safe(ticker):
    try:
        df = sc.fetch_data(ticker)
        if df is None or len(df) < 30:
            return {"ticker": ticker, "signal": "—", "score": 50,
                    "confidence": "—", "confidence_pct": None,
                    "confidence_basis": "uncalibrated", "confidence_trusted": False,
                    "trade_plan": None, "tradable": False, "liquidity": {},
                    "liquidity_note": "", "risk": "—", "is_penny": False,
                    "regime": "—", "adx": 0, "confluence": {},
                    "reasons": ["Insufficient data"], "price": 0,
                    "rsi": 50, "macd_hist": 0, "volume_ratio": 1,
                    "volume_spike": False, "supertrend": 0,
                    "above_vwap": False, "obv_slope": 0,
                    "mfi": 50, "williams_r": -50, "patterns": {},
                    "ema_9": 0, "ema_21": 0, "bb_pct_b": 0.5, "atr": 0,
                    "error": "Insufficient data", "ts": datetime.now().strftime("%H:%M:%S")}
        price = float(df["Close"].iloc[-1])
        is_penny = price < config.PENNY_STOCK_MAX_PRICE
        ind = indicators.run_all(df)
        result = sig_engine.generate_signal(ind, ticker, is_penny=is_penny)
        return _result_to_dict(result)
    except Exception as e:
        return {"ticker": ticker, "signal": "—", "score": 50,
                "confidence": "—", "risk": "—", "is_penny": False,
                "regime": "—", "adx": 0, "confluence": {},
                "reasons": [str(e)], "price": 0,
                "rsi": 50, "macd_hist": 0, "volume_ratio": 1,
                "volume_spike": False, "supertrend": 0,
                "above_vwap": False, "obv_slope": 0,
                "mfi": 50, "williams_r": -50, "patterns": {},
                "ema_9": 0, "ema_21": 0, "bb_pct_b": 0.5, "atr": 0,
                "error": str(e), "ts": datetime.now().strftime("%H:%M:%S")}

# ── Routes ───────────────────────────────────────────────────────

@app.route("/")
def index():
    """Cinematic marketing landing page (THE TAPE)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landing.html")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return render_template_string(DASHBOARD_HTML)  # fall back to the app


@app.route("/app")
@app.route("/dashboard")
def dashboard():
    """The live signal terminal."""
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/state")
def api_state():
    with _lock:
        return jsonify({
            "watchlist":    _state["watchlist"],
            "last_results": _state["last_results"],
            "last_scan_ts": _state["last_scan_ts"],
            "scanning":     _state["scanning"],
        })


@app.route("/api/scan-all", methods=["POST"])
def api_scan_all():
    with _lock:
        if _state["scanning"]:
            return jsonify({"error": "Scan already in progress"}), 429
        _state["scanning"] = True
        watchlist = list(_state["watchlist"])

    def do_scan():
        results = []
        for t in watchlist:
            results.append(_scan_ticker_safe(t))
            time.sleep(0.2)
        results.sort(key=lambda r: r["score"], reverse=True)
        notify.dispatch(results)  # mobile push for actionable signals (cooldown inside)
        with _lock:
            _state["last_results"] = results
            _state["last_scan_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _state["scanning"] = False

    threading.Thread(target=do_scan, daemon=True).start()
    return jsonify({"status": "scanning", "count": len(watchlist)})


@app.route("/api/scan/<ticker>", methods=["POST"])
def api_scan_ticker(ticker):
    ticker = ticker.upper().strip()
    result = _scan_ticker_safe(ticker)
    notify.dispatch([result])
    return jsonify(result)


@app.route("/api/commentary/<ticker>", methods=["POST"])
def api_commentary(ticker):
    """Optional LLM desk note. Returns {enabled, note}. Off when no API key."""
    ticker = ticker.upper().strip()
    if not commentary.is_enabled():
        return jsonify({
            "enabled": False,
            "note": "AI commentary is off — set ANTHROPIC_API_KEY and "
                    "`pip install anthropic` to enable.",
        })
    try:
        full = sc.scan_ticker(ticker)  # rich result (has indicators + plan)
        note = commentary.generate(full) if full else None
        return jsonify({"enabled": True, "note": note or "Commentary unavailable."})
    except Exception as e:
        return jsonify({"enabled": True, "note": f"Commentary error: {e}"}), 200


@app.route("/api/watchlist", methods=["GET"])
def api_get_watchlist():
    with _lock:
        return jsonify(_state["watchlist"])


@app.route("/api/watchlist", methods=["POST"])
def api_set_watchlist():
    data = request.get_json()
    tickers = [t.upper().strip() for t in data.get("tickers", []) if t.strip()]
    with _lock:
        _state["watchlist"] = tickers
    return jsonify({"watchlist": tickers})


@app.route("/api/watchlist/<ticker>", methods=["DELETE"])
def api_remove_ticker(ticker):
    ticker = ticker.upper()
    with _lock:
        _state["watchlist"] = [t for t in _state["watchlist"] if t != ticker]
        return jsonify({"watchlist": _state["watchlist"]})


# ── Dashboard HTML ───────────────────────────────────────────────
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trading Signal Bot</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;
    --muted:#8b949e;--buy:#2ea043;--sell:#da3633;--hold:#d29922;
    --strong-buy:#3fb950;--strong-sell:#f85149;--accent:#388bfd;
    --ranging:#6e7681;--trending:#58a6ff;
  }
  body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;min-height:100vh}
  
  /* Header */
  .header{background:var(--card);border-bottom:1px solid var(--border);padding:16px 24px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
  .header h1{font-size:20px;font-weight:700;letter-spacing:.5px}
  .header h1 span{color:var(--accent)}
  .header-right{margin-left:auto;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  .last-scan{color:var(--muted);font-size:12px}
  
  /* Buttons */
  .btn{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600;transition:opacity .15s}
  .btn:hover{opacity:.85}
  .btn:disabled{opacity:.4;cursor:not-allowed}
  .btn-primary{background:var(--accent);color:#fff}
  .btn-success{background:var(--buy);color:#fff}
  .btn-danger{background:var(--sell);color:#fff}
  .btn-ghost{background:transparent;color:var(--muted);border:1px solid var(--border)}
  
  /* Layout */
  .container{max-width:1400px;margin:0 auto;padding:20px 24px}
  
  /* Controls bar */
  .controls{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap;align-items:flex-end}
  .input-group{display:flex;gap:8px;align-items:center}
  .input-group input{background:var(--card);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:6px;font-size:13px;width:120px}
  .input-group input:focus{outline:none;border-color:var(--accent)}
  .auto-label{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:13px;cursor:pointer}
  .auto-label input{cursor:pointer}
  
  /* Watchlist */
  .watchlist-bar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:20px;padding:12px;background:var(--card);border:1px solid var(--border);border-radius:8px;align-items:center}
  .watchlist-bar span{color:var(--muted);font-size:12px;margin-right:4px}
  .ticker-chip{display:inline-flex;align-items:center;gap:4px;background:#21262d;border:1px solid var(--border);border-radius:4px;padding:3px 8px;font-size:12px;font-weight:600}
  .ticker-chip button{background:none;border:none;color:var(--muted);cursor:pointer;font-size:14px;line-height:1;padding:0 0 0 2px}
  .ticker-chip button:hover{color:var(--sell)}
  
  /* Signal grid */
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
  
  /* Signal card */
  .card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;cursor:pointer;transition:border-color .15s}
  .card:hover{border-color:var(--accent)}
  .card.buy-card{border-left:3px solid var(--buy)}
  .card.sell-card{border-left:3px solid var(--sell)}
  .card.hold-card{border-left:3px solid var(--hold)}
  .card.error-card{border-left:3px solid var(--ranging);opacity:.6}
  
  .card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
  .ticker-symbol{font-size:18px;font-weight:700}
  .price{color:var(--muted);font-size:12px;margin-top:2px}
  
  .signal-badge{padding:5px 12px;border-radius:20px;font-size:13px;font-weight:700;text-transform:uppercase}
  .badge-BUY{background:rgba(46,160,67,.2);color:var(--strong-buy);border:1px solid var(--buy)}
  .badge-SELL{background:rgba(218,54,51,.2);color:var(--strong-sell);border:1px solid var(--sell)}
  .badge-HOLD{background:rgba(210,153,34,.15);color:var(--hold);border:1px solid var(--hold)}
  .badge---{background:rgba(110,118,129,.1);color:var(--muted);border:1px solid var(--border)}
  
  /* Score bar */
  .score-row{display:flex;align-items:center;gap:10px;margin-bottom:10px}
  .score-num{font-size:24px;font-weight:700;min-width:38px}
  .score-bar-wrap{flex:1;background:#21262d;border-radius:4px;height:8px;overflow:hidden}
  .score-bar{height:100%;border-radius:4px;transition:width .5s}
  .bar-buy{background:linear-gradient(90deg,#2ea043,#3fb950)}
  .bar-sell{background:linear-gradient(90deg,#da3633,#f85149)}
  .bar-hold{background:var(--hold)}
  .bar-none{background:var(--ranging)}
  
  /* Metrics row */
  .metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:10px}
  .metric{text-align:center;padding:6px;background:#0d1117;border-radius:4px}
  .metric-val{font-size:13px;font-weight:600}
  .metric-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
  
  /* Tags */
  .tags{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px}
  .tag{padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600}
  .tag-trending{background:rgba(88,166,255,.15);color:var(--trending)}
  .tag-ranging{background:rgba(110,118,129,.15);color:var(--ranging)}
  .tag-spike{background:rgba(210,153,34,.15);color:var(--hold)}
  .tag-penny{background:rgba(163,113,247,.15);color:#a371f7}
  .tag-risk-HIGH{background:rgba(218,54,51,.15);color:#f85149}
  .tag-risk-MEDIUM{background:rgba(210,153,34,.15);color:var(--hold)}
  .tag-risk-LOW{background:rgba(46,160,67,.15);color:var(--strong-buy)}
  
  /* Top reason */
  .top-reason{color:var(--muted);font-size:12px;line-height:1.4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  
  /* Confluence meter */
  .confluence{display:flex;align-items:center;gap:8px;margin-top:8px;font-size:11px;color:var(--muted)}
  .conf-dot{width:8px;height:8px;border-radius:50%;display:inline-block}
  .conf-buy{background:var(--buy)}
  .conf-sell{background:var(--sell)}
  
  /* Detail panel */
  .detail-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;overflow:auto}
  .detail-overlay.open{display:flex;align-items:flex-start;justify-content:center;padding:40px 20px}
  .detail-panel{background:var(--card);border:1px solid var(--border);border-radius:12px;width:100%;max-width:640px;padding:24px}
  .detail-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
  .detail-header h2{font-size:22px;font-weight:700}
  .detail-close{background:none;border:none;color:var(--muted);font-size:22px;cursor:pointer;line-height:1}
  .detail-close:hover{color:var(--text)}
  
  .detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px}
  .detail-metric{background:#0d1117;border-radius:6px;padding:10px 12px}
  .detail-metric-val{font-size:18px;font-weight:700}
  .detail-metric-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:2px}
  
  .reasons-list{list-style:none}
  .reasons-list li{padding:6px 0;border-bottom:1px solid #21262d;font-size:13px;color:var(--text);display:flex;align-items:flex-start;gap:8px}
  .reasons-list li::before{content:"•";color:var(--accent);flex-shrink:0;margin-top:1px}
  .reasons-list li:last-child{border-bottom:none}
  
  .patterns-list{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
  .pattern-tag{padding:3px 8px;border-radius:4px;font-size:11px;font-weight:600}
  .pattern-bullish{background:rgba(46,160,67,.2);color:var(--strong-buy)}
  .pattern-bearish{background:rgba(218,54,51,.2);color:var(--strong-sell)}
  .pattern-neutral{background:rgba(110,118,129,.2);color:var(--muted)}
  
  /* Spinner */
  .spinner{display:inline-block;width:16px;height:16px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px}
  @keyframes spin{to{transform:rotate(360deg)}}
  
  /* Empty state */
  .empty{text-align:center;padding:60px 20px;color:var(--muted)}
  .empty-icon{font-size:48px;margin-bottom:16px}
  .empty h3{font-size:18px;margin-bottom:8px;color:var(--text)}
  
  /* Section title */
  .section-title{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:12px;font-weight:600}
  
  /* Scanning overlay on cards */
  .scanning-pulse{animation:pulse 1.5s ease-in-out infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>📈 Trading Signal <span>Bot</span></h1>
  </div>
  <div class="header-right">
    <span class="last-scan" id="lastScanTime">Never scanned</span>
    <label class="auto-label">
      <input type="checkbox" id="autoRefresh"> Auto-refresh (60s)
    </label>
    <button class="btn btn-primary" id="scanBtn" onclick="scanAll()">
      Scan All
    </button>
  </div>
</div>

<div class="container">
  <!-- Controls -->
  <div class="controls">
    <div class="input-group">
      <input type="text" id="singleTicker" placeholder="e.g. AAPL" maxlength="10"
             onkeydown="if(event.key==='Enter') deepScan()">
      <button class="btn btn-success" onclick="deepScan()">Deep Scan</button>
    </div>
    <div class="input-group">
      <input type="text" id="addTickerInput" placeholder="Add ticker…" maxlength="10"
             onkeydown="if(event.key==='Enter') addToWatchlist()">
      <button class="btn btn-ghost" onclick="addToWatchlist()">+ Add</button>
    </div>
  </div>

  <!-- Watchlist chips -->
  <div class="watchlist-bar" id="watchlistBar">
    <span>Watchlist:</span>
  </div>

  <!-- Signal grid -->
  <div class="section-title" id="gridTitle">SIGNALS</div>
  <div class="grid" id="signalGrid">
    <div class="empty">
      <div class="empty-icon">📊</div>
      <h3>No signals yet</h3>
      <p>Click <strong>Scan All</strong> to fetch live market data and generate signals.</p>
    </div>
  </div>
</div>

<!-- Detail panel overlay -->
<div class="detail-overlay" id="detailOverlay" onclick="closeDetail(event)">
  <div class="detail-panel" id="detailPanel">
    <div class="detail-header">
      <h2 id="detailTitle">—</h2>
      <button class="detail-close" onclick="closeDetail()">✕</button>
    </div>
    <div id="detailBody"></div>
  </div>
</div>

<script>
let autoTimer = null;
let currentResults = [];
let scanning = false;

// ── Watchlist ─────────────────────────────────────────────────

async function loadWatchlist() {
  const r = await fetch('/api/watchlist');
  const wl = await r.json();
  renderWatchlist(wl);
}

function renderWatchlist(wl) {
  const bar = document.getElementById('watchlistBar');
  bar.innerHTML = '<span>Watchlist:</span>';
  wl.forEach(t => {
    const chip = document.createElement('div');
    chip.className = 'ticker-chip';
    chip.innerHTML = `${t}<button onclick="removeTicker('${t}')" title="Remove">×</button>`;
    bar.appendChild(chip);
  });
}

async function addToWatchlist() {
  const input = document.getElementById('addTickerInput');
  const t = input.value.trim().toUpperCase();
  if (!t) return;
  input.value = '';
  const r = await fetch('/api/watchlist');
  const wl = await r.json();
  if (!wl.includes(t)) {
    wl.push(t);
    await fetch('/api/watchlist', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({tickers: wl})});
    renderWatchlist(wl);
  }
}

async function removeTicker(t) {
  await fetch(`/api/watchlist/${t}`, {method:'DELETE'});
  await loadWatchlist();
}

// ── Scanning ──────────────────────────────────────────────────

async function scanAll() {
  if (scanning) return;
  scanning = true;
  const btn = document.getElementById('scanBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Scanning…';
  showScanningState();
  await fetch('/api/scan-all', {method:'POST'});
  pollState();
}

function pollState() {
  const interval = setInterval(async () => {
    const r = await fetch('/api/state');
    const state = await r.json();
    if (!state.scanning) {
      clearInterval(interval);
      scanning = false;
      const btn = document.getElementById('scanBtn');
      btn.disabled = false;
      btn.innerHTML = 'Scan All';
      currentResults = state.last_results;
      renderGrid(currentResults);
      if (state.last_scan_ts) {
        document.getElementById('lastScanTime').textContent = 'Last scan: ' + state.last_scan_ts;
      }
    }
  }, 800);
}

function showScanningState() {
  const grid = document.getElementById('signalGrid');
  // Show skeleton cards while scanning
  grid.innerHTML = '';
  const wl = document.querySelectorAll('.ticker-chip');
  const count = Math.max(wl.length, 6);
  for (let i = 0; i < count; i++) {
    const div = document.createElement('div');
    div.className = 'card scanning-pulse';
    div.style.height = '180px';
    div.innerHTML = '<div style="color:var(--muted);display:flex;align-items:center;height:100%;justify-content:center"><span class="spinner"></span>Fetching data…</div>';
    grid.appendChild(div);
  }
}

async function deepScan() {
  const input = document.getElementById('singleTicker');
  const t = input.value.trim().toUpperCase();
  if (!t) { input.focus(); return; }
  const btn = document.querySelector('[onclick="deepScan()"]');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Scanning…';
  const r = await fetch(`/api/scan/${t}`, {method:'POST'});
  const result = await r.json();
  btn.disabled = false;
  btn.innerHTML = 'Deep Scan';
  showDetail(result);
}

// ── Rendering ─────────────────────────────────────────────────

function scoreBarClass(signal, score) {
  if (signal === 'BUY') return 'bar-buy';
  if (signal === 'SELL') return 'bar-sell';
  if (signal === 'HOLD') return 'bar-hold';
  return 'bar-none';
}

function renderCard(r) {
  const sig = r.signal || '—';
  const cardClass = sig === 'BUY' ? 'buy-card' : sig === 'SELL' ? 'sell-card' : sig === 'HOLD' ? 'hold-card' : 'error-card';
  const barClass = scoreBarClass(sig, r.score);
  const scoreColor = sig === 'BUY' ? '#3fb950' : sig === 'SELL' ? '#f85149' : sig === 'HOLD' ? '#d29922' : '#6e7681';
  const barWidth = r.score + '%';
  
  const regimeTag = r.regime === 'TRENDING' ?
    `<span class="tag tag-trending">TRENDING ADX ${r.adx}</span>` :
    r.regime === 'RANGING' ?
    `<span class="tag tag-ranging">RANGING ADX ${r.adx}</span>` :
    `<span class="tag tag-ranging">ADX ${r.adx}</span>`;
  
  const spikeTag = r.volume_spike ? '<span class="tag tag-spike">🔥 VOL SPIKE</span>' : '';
  const pennyTag = r.is_penny ? '<span class="tag tag-penny">PENNY</span>' : '';
  const riskTag = `<span class="tag tag-risk-${r.risk}">${r.risk} RISK</span>`;
  
  const topReason = r.reasons && r.reasons.length > 0 ?
    r.reasons.find(r => !r.includes('Confluence gate')) || r.reasons[0] : '—';
  
  const confBuys = r.confluence ? r.confluence.buys || 0 : 0;
  const confSells = r.confluence ? r.confluence.sells || 0 : 0;
  const confDots = Array(Math.min(confBuys,5)).fill('<span class="conf-dot conf-buy"></span>').join('') +
                   Array(Math.min(confSells,5)).fill('<span class="conf-dot conf-sell"></span>').join('');
  
  return `
<div class="card ${cardClass}" onclick='showDetail(${JSON.stringify(r).replace(/'/g,"&#39;")})'>
  <div class="card-header">
    <div>
      <div class="ticker-symbol">${r.ticker}</div>
      <div class="price">$${r.price.toFixed(4)}</div>
    </div>
    <span class="signal-badge badge-${sig}">${sig}</span>
  </div>
  <div class="score-row">
    <div class="score-num" style="color:${scoreColor}">${r.score}</div>
    <div class="score-bar-wrap">
      <div class="score-bar ${barClass}" style="width:${barWidth}"></div>
    </div>
  </div>
  <div class="metrics">
    <div class="metric"><div class="metric-val">${r.rsi}</div><div class="metric-label">RSI</div></div>
    <div class="metric"><div class="metric-val">${r.mfi}</div><div class="metric-label">MFI</div></div>
    <div class="metric"><div class="metric-val">${r.volume_ratio}×</div><div class="metric-label">Vol</div></div>
  </div>
  <div class="tags">${regimeTag}${spikeTag}${pennyTag}${riskTag}</div>
  <div class="top-reason">${topReason}</div>
  <div class="confluence">${confDots}<span style="margin-left:4px">${confBuys} buy / ${confSells} sell confirms</span></div>
</div>`;
}

function renderGrid(results) {
  const grid = document.getElementById('signalGrid');
  const title = document.getElementById('gridTitle');
  if (!results || results.length === 0) {
    grid.innerHTML = '<div class="empty"><div class="empty-icon">📊</div><h3>No signals yet</h3><p>Click <strong>Scan All</strong> to fetch live market data.</p></div>';
    return;
  }
  const buys  = results.filter(r => r.signal === 'BUY').length;
  const sells = results.filter(r => r.signal === 'SELL').length;
  const holds = results.filter(r => r.signal === 'HOLD').length;
  title.textContent = `SIGNALS — ${buys} BUY · ${sells} SELL · ${holds} HOLD`;
  grid.innerHTML = results.map(renderCard).join('');
}

// ── Detail panel ──────────────────────────────────────────────

function showDetail(r) {
  const sig = r.signal || '—';
  const scoreColor = sig === 'BUY' ? '#3fb950' : sig === 'SELL' ? '#f85149' : '#d29922';
  const barClass = scoreBarClass(sig, r.score);

  // Calibrated confidence — measured hit-rate, not a label.
  let confLine;
  if (r.confidence_pct != null && r.confidence_basis === 'calibrated') {
    const trust = r.confidence_trusted ? '' : ' (low sample)';
    confLine = `<b style="color:${scoreColor}">${r.confidence_pct}% calibrated</b> hit-rate to TP1${trust} · ${r.confidence} · ${r.risk} risk · ${r.regime||'—'} (ADX ${r.adx})`;
  } else {
    confLine = `${r.confidence} confidence (uncalibrated) · ${r.risk} risk · ${r.regime||'—'} (ADX ${r.adx})`;
  }

  // Trade plan block (BUY/SELL only).
  const p = r.trade_plan;
  const planHtml = p ? `
    <div style="margin-top:12px"><div class="section-title">TRADE PLAN (${sig})</div>
    <div class="detail-grid" style="grid-template-columns:repeat(4,1fr)">
      <div class="detail-metric"><div class="detail-metric-val">$${p.entry}</div><div class="detail-metric-label">Entry</div></div>
      <div class="detail-metric"><div class="detail-metric-val" style="color:#f85149">$${p.stop}</div><div class="detail-metric-label">Stop</div></div>
      <div class="detail-metric"><div class="detail-metric-val" style="color:#3fb950">$${p.tp1}</div><div class="detail-metric-label">TP1 (1R)</div></div>
      <div class="detail-metric"><div class="detail-metric-val" style="color:#3fb950">$${p.tp2}</div><div class="detail-metric-label">TP2 (2R)</div></div>
    </div></div>` : '';

  // Liquidity line.
  const liq = r.liquidity || {};
  const liqHtml = liq.avg_daily_dollar_vol != null ? `
    <div style="margin-top:8px;color:var(--muted);font-size:12px">
      Liquidity: $${(liq.avg_daily_dollar_vol/1e6).toFixed(1)}M/day · ${(liq.avg_daily_volume||0).toLocaleString()} sh/day
      ${r.tradable ? '' : ' · <span style="color:#f85149">⚠ '+(r.liquidity_note||'illiquid')+'</span>'}
    </div>` : '';
  
  const patternsHtml = Object.entries(r.patterns || {}).length > 0 ?
    `<div style="margin-top:12px"><div class="section-title">PATTERNS</div>
    <div class="patterns-list">${Object.entries(r.patterns).map(([k,v]) =>
      `<span class="pattern-tag pattern-${v}">${k.replace(/_/g,' ')}</span>`).join('')}</div></div>` : '';

  const reasonsHtml = (r.reasons || []).map(r =>
    `<li>${r}</li>`).join('');

  document.getElementById('detailTitle').innerHTML =
    `${r.ticker} <span class="signal-badge badge-${sig}" style="font-size:14px;vertical-align:middle">${sig}</span>`;
  
  document.getElementById('detailBody').innerHTML = `
    <div style="margin-bottom:16px">
      <div class="score-row" style="margin-bottom:6px">
        <div class="score-num" style="color:${scoreColor};font-size:32px">${r.score}</div>
        <div class="score-bar-wrap" style="height:12px">
          <div class="score-bar ${barClass}" style="width:${r.score}%"></div>
        </div>
      </div>
      <div style="font-size:12px">${confLine}</div>
      ${liqHtml}
    </div>
    ${planHtml}
    <div style="margin-top:16px">
      <div class="section-title">AI DESK NOTE</div>
      <button class="btn btn-ghost" id="commentaryBtn" onclick="getCommentary('${r.ticker}')">🧠 Generate desk note</button>
      <div id="commentaryBox" style="margin-top:10px;white-space:pre-wrap;font-size:13px;line-height:1.5;color:var(--text)"></div>
    </div>
    <div class="detail-grid">
      <div class="detail-metric"><div class="detail-metric-val">$${r.price.toFixed(4)}</div><div class="detail-metric-label">Price</div></div>
      <div class="detail-metric"><div class="detail-metric-val">${r.rsi}</div><div class="detail-metric-label">RSI (14)</div></div>
      <div class="detail-metric"><div class="detail-metric-val">${r.mfi}</div><div class="detail-metric-label">MFI</div></div>
      <div class="detail-metric"><div class="detail-metric-val">${r.williams_r}</div><div class="detail-metric-label">Williams %R</div></div>
      <div class="detail-metric"><div class="detail-metric-val">${r.volume_ratio}×${r.volume_spike ? ' 🔥' : ''}</div><div class="detail-metric-label">Volume Ratio</div></div>
      <div class="detail-metric"><div class="detail-metric-val">${r.supertrend === 1 ? '🟢 Bullish' : '🔴 Bearish'}</div><div class="detail-metric-label">Supertrend</div></div>
      <div class="detail-metric"><div class="detail-metric-val">${r.above_vwap ? '🟢 Above' : '🔴 Below'}</div><div class="detail-metric-label">VWAP</div></div>
      <div class="detail-metric"><div class="detail-metric-val">${r.macd_hist > 0 ? '+' : ''}${r.macd_hist.toFixed(4)}</div><div class="detail-metric-label">MACD Hist</div></div>
      <div class="detail-metric"><div class="detail-metric-val">${r.ema_9.toFixed(3)} / ${r.ema_21.toFixed(3)}</div><div class="detail-metric-label">EMA 9 / 21</div></div>
      <div class="detail-metric"><div class="detail-metric-val">${(r.bb_pct_b * 100).toFixed(1)}%</div><div class="detail-metric-label">BB %B</div></div>
      <div class="detail-metric"><div class="detail-metric-val">${r.confluence ? r.confluence.buys : 0} buy / ${r.confluence ? r.confluence.sells : 0} sell</div><div class="detail-metric-label">Confluence</div></div>
      <div class="detail-metric"><div class="detail-metric-val">${r.atr.toFixed(4)}</div><div class="detail-metric-label">ATR (14)</div></div>
    </div>
    ${patternsHtml}
    <div style="margin-top:16px">
      <div class="section-title">SIGNAL REASONS</div>
      <ul class="reasons-list">${reasonsHtml}</ul>
    </div>
    <div style="margin-top:16px;text-align:right">
      <button class="btn btn-primary" onclick="rescanFromDetail('${r.ticker}')">
        ↻ Re-scan ${r.ticker}
      </button>
    </div>`;
  
  document.getElementById('detailOverlay').classList.add('open');
}

async function getCommentary(ticker) {
  const btn = document.getElementById('commentaryBtn');
  const box = document.getElementById('commentaryBox');
  if (!btn || !box) return;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Thinking…';
  box.textContent = '';
  try {
    const r = await fetch(`/api/commentary/${ticker}`, {method:'POST'});
    const data = await r.json();
    box.textContent = data.note || '(no commentary)';
  } catch (e) {
    box.textContent = 'Commentary request failed.';
  }
  btn.disabled = false;
  btn.innerHTML = '🧠 Generate desk note';
}

async function rescanFromDetail(ticker) {
  const body = document.getElementById('detailBody');
  body.style.opacity = '0.4';
  const r = await fetch(`/api/scan/${ticker}`, {method:'POST'});
  const result = await r.json();
  body.style.opacity = '1';
  showDetail(result);
  // Update in main grid
  currentResults = currentResults.map(x => x.ticker === ticker ? result : x);
  renderGrid(currentResults);
}

function closeDetail(e) {
  if (!e || e.target === document.getElementById('detailOverlay')) {
    document.getElementById('detailOverlay').classList.remove('open');
  }
}

// ── Auto-refresh ──────────────────────────────────────────────

document.getElementById('autoRefresh').addEventListener('change', function() {
  if (this.checked) {
    autoTimer = setInterval(scanAll, 60000);
  } else {
    clearInterval(autoTimer);
  }
});

// ── Init ──────────────────────────────────────────────────────

async function init() {
  await loadWatchlist();
  const r = await fetch('/api/state');
  const state = await r.json();
  if (state.last_results && state.last_results.length > 0) {
    currentResults = state.last_results;
    renderGrid(currentResults);
    if (state.last_scan_ts) {
      document.getElementById('lastScanTime').textContent = 'Last scan: ' + state.last_scan_ts;
    }
  }
}

init();
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("\n  📈  Trading Signal Bot — Web Dashboard")
    print("  ─────────────────────────────────────────")
    print("  Open:  http://localhost:5000")
    print("  Stop:  Ctrl+C\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
