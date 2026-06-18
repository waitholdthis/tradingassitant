# ============================================================
# TICKER UNIVERSE
# Downloads the full list of US-listed stocks from SEC EDGAR's
# public company tickers endpoint (~10,000 tickers, same stocks
# Webull lists). Cached locally for 24h.
# ============================================================

import datetime
import os
import requests

CACHE_FILE = ".ticker_universe_cache.txt"
CACHE_TTL_HOURS = 24
_TIMEOUT = 20

SEC_URL = "https://www.sec.gov/files/company_tickers.json"
_HEADERS = {"User-Agent": "tradingbot parker.tootill@gmail.com"}

# Suffixes that flag warrants, rights, units — not useful for momentum signals.
_SKIP_SUFFIXES = ("W", "R", "U", "WS", "WT")


def _skip(sym: str) -> bool:
    if not sym or len(sym) > 5:
        return True
    for s in _SKIP_SUFFIXES:
        if sym.endswith(s) and len(sym) > 4:
            return True
    return False


def _fetch() -> list[str]:
    resp = requests.get(SEC_URL, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    tickers = []
    for entry in data.values():
        sym = entry.get("ticker", "").strip().upper()
        if not sym or _skip(sym):
            continue
        tickers.append(sym)
    return sorted(set(tickers))


def _cache_fresh() -> bool:
    if not os.path.exists(CACHE_FILE):
        return False
    age_hours = (
        datetime.datetime.now()
        - datetime.datetime.fromtimestamp(os.path.getmtime(CACHE_FILE))
    ).total_seconds() / 3600
    return age_hours < CACHE_TTL_HOURS


def get_universe(force_refresh: bool = False) -> list[str]:
    """Return the full list of US-listed ticker symbols.

    Downloads from SEC EDGAR on first call or when the 24-hour cache expires.
    """
    if not force_refresh and _cache_fresh():
        with open(CACHE_FILE) as f:
            return [line.strip() for line in f if line.strip()]

    print("  Fetching ticker universe from SEC EDGAR (one-time download)...")
    try:
        tickers = _fetch()
    except Exception as e:
        print(f"  ⚠ Could not download ticker list: {e}")
        if os.path.exists(CACHE_FILE):
            print("  Using stale cache.")
            with open(CACHE_FILE) as f:
                return [line.strip() for line in f if line.strip()]
        raise

    with open(CACHE_FILE, "w") as f:
        f.write("\n".join(tickers))

    print(f"  {len(tickers):,} tickers loaded and cached.")
    return tickers
