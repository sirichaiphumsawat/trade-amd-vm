"""
exchange_utils.py — Bulletproof multi-exchange fallback for all scripts

Solves: GH Actions runner IPs get geo-blocked (HTTP 451/403) or SSL errors
from Binance futures, Binance spot, Bybit, and sometimes even data-api.binance.vision.

Strategy:
  1. ccxt exchanges: binanceusdm → binance → bybit
  2. Raw HTTP endpoints: data-api.binance.vision → Bybit public v5
  3. All HTTP calls go through _urlopen() which handles SSL cert issues
  4. Every exchange attempt catches ALL exceptions (not just 451/403)
"""

import json
import ssl
import time
import urllib.request
from typing import Optional

import ccxt
import pandas as pd

# ---------------------------------------------------------------------------
# SSL-safe urlopen — some GH runners have broken cert chains
# ---------------------------------------------------------------------------
_SSL_CTX: Optional[ssl.SSLContext] = None


def _get_ssl_ctx() -> ssl.SSLContext:
    global _SSL_CTX
    if _SSL_CTX is None:
        _SSL_CTX = ssl.create_default_context()
    return _SSL_CTX


def _urlopen(url: str, timeout: int = 15):
    """urlopen with SSL fallback: try verified first, then unverified."""
    headers = {"User-Agent": "Mozilla/5.0 trade-amd-vm/1.0"}
    req = urllib.request.Request(url, headers=headers)
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=_get_ssl_ctx())
    except ssl.SSLError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)


# ---------------------------------------------------------------------------
# Raw HTTP exchange backends (no ccxt dependency)
# ---------------------------------------------------------------------------
class _BinanceVisionAPI:
    """data-api.binance.vision — public, usually not geo-blocked."""

    def load_markets(self):
        return {}

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=1000):
        sym = symbol.replace("/", "").replace(":USDT", "")
        url = (
            f"https://data-api.binance.vision/api/v3/klines"
            f"?symbol={sym}&interval={timeframe}&limit={min(limit, 1000)}"
        )
        if since:
            url += f"&startTime={since}"
        data = json.loads(_urlopen(url).read())
        return [
            [int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])]
            for c in data
        ]


class _BybitPublicAPI:
    """Bybit v5 public market data — different infra from Binance."""

    _TF_MAP = {
        "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
        "1h": "60", "2h": "120", "4h": "240", "1d": "D", "1w": "W",
    }

    def load_markets(self):
        return {}

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=1000):
        interval = self._TF_MAP.get(timeframe, timeframe)
        url = (
            f"https://api.bybit.com/v5/market/kline"
            f"?category=linear&symbol=BTCUSDT&interval={interval}&limit={min(limit, 1000)}"
        )
        if since:
            url += f"&start={since}"
        resp = json.loads(_urlopen(url).read())
        rows = resp.get("result", {}).get("list", [])
        out = []
        for r in rows:
            out.append([int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
        out.sort(key=lambda x: x[0])
        return out


class _OKXPublicAPI:
    """OKX v5 public market data — yet another infra."""

    _TF_MAP = {
        "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1H", "2h": "2H", "4h": "4H", "1d": "1D",
    }

    def load_markets(self):
        return {}

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=300):
        bar = self._TF_MAP.get(timeframe, timeframe)
        url = (
            f"https://www.okx.com/api/v5/market/candles"
            f"?instId=BTC-USDT-SWAP&bar={bar}&limit={min(limit, 300)}"
        )
        if since:
            url += f"&after={since}"
        resp = json.loads(_urlopen(url).read())
        rows = resp.get("data", [])
        out = []
        for r in rows:
            out.append([int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
        out.sort(key=lambda x: x[0])
        return out


# ---------------------------------------------------------------------------
# make_exchange() — single function all scripts should call
# ---------------------------------------------------------------------------
def make_exchange():
    """Try every exchange until one works. Returns (exchange, symbol_str).

    Catches ALL exceptions per candidate, not just 451/403.
    """
    candidates = [
        ("binanceusdm", "BTC/USDT:USDT", lambda: ccxt.binanceusdm({"enableRateLimit": True})),
        ("binance",     "BTC/USDT",      lambda: ccxt.binance({"enableRateLimit": True})),
        ("bybit-ccxt",  "BTC/USDT:USDT", lambda: ccxt.bybit({"enableRateLimit": True})),
        ("data-vision", "BTCUSDT",       lambda: _BinanceVisionAPI()),
        ("bybit-raw",   "BTCUSDT",       lambda: _BybitPublicAPI()),
        ("okx-raw",     "BTCUSDT",       lambda: _OKXPublicAPI()),
    ]
    errors = []
    for name, symbol, factory in candidates:
        try:
            ex = factory()
            ex.load_markets()
            ohlcv = ex.fetch_ohlcv(symbol, "15m", limit=2)
            if not ohlcv:
                raise RuntimeError("fetch_ohlcv returned empty")
            if name != "binanceusdm":
                print(f"[fallback] using {name} ({symbol})", flush=True)
            return ex, symbol
        except Exception as e:
            errors.append(f"{name}: {e}")
            print(f"[exchange] {name} failed: {e}", flush=True)
            continue
    raise RuntimeError(
        f"ALL exchanges failed ({len(candidates)} tried):\n" + "\n".join(errors)
    )


# ---------------------------------------------------------------------------
# fetch_klines_raw() — for chart_setup.py and similar simple fetchers
# ---------------------------------------------------------------------------
def fetch_klines_raw(symbol: str = "BTCUSDT", tf: str = "15m", limit: int = 200) -> list:
    """Fetch klines as raw list of lists. Multi-endpoint fallback."""
    endpoints = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={tf}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={tf}&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={tf}&limit={limit}",
    ]
    for url in endpoints:
        try:
            return json.loads(_urlopen(url).read())
        except Exception as e:
            print(f"[klines] {url.split('/')[2]} failed: {e}", flush=True)
    try:
        ex = _BybitPublicAPI()
        rows = ex.fetch_ohlcv(symbol, tf, limit=limit)
        return [[r[0], str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]),
                 r[0] + 60000, "0", 0, "0", "0", "0"] for r in rows]
    except Exception as e:
        print(f"[klines] bybit-raw failed: {e}", flush=True)
    raise RuntimeError("fetch_klines_raw: all endpoints failed")


def fetch_price(symbol: str = "BTCUSDT") -> float:
    """Fetch latest price. Multi-endpoint fallback."""
    endpoints = [
        (f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}", lambda d: float(d["price"])),
        (f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", lambda d: float(d["price"])),
        (f"https://data-api.binance.vision/api/v3/ticker/price?symbol={symbol}", lambda d: float(d["price"])),
        (f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}",
         lambda d: float(d["result"]["list"][0]["lastPrice"])),
        (f"https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT-SWAP",
         lambda d: float(d["data"][0]["last"])),
    ]
    for url, extract in endpoints:
        try:
            data = json.loads(_urlopen(url, timeout=10).read())
            return extract(data)
        except Exception as e:
            print(f"[price] {url.split('/')[2]} failed: {e}", flush=True)
    raise RuntimeError("fetch_price: all endpoints failed")


def fetch_ticker_24h(symbol: str = "BTCUSDT") -> Optional[dict]:
    """Fetch 24h ticker stats. Returns dict with price/open/high/low/change/volume or None."""
    binance_endpoints = [
        f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}",
        f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}",
        f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol={symbol}",
    ]
    for url in binance_endpoints:
        try:
            d = json.loads(_urlopen(url, timeout=10).read())
            return {
                "price": float(d["lastPrice"]),
                "open": float(d["openPrice"]),
                "high": float(d["highPrice"]),
                "low": float(d["lowPrice"]),
                "change": float(d["priceChangePercent"]),
                "volume": float(d["quoteVolume"]) / 1e9,
            }
        except Exception as e:
            print(f"[24h] {url.split('/')[2]} failed: {e}", flush=True)
    try:
        url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}"
        d = json.loads(_urlopen(url, timeout=10).read())
        t = d["result"]["list"][0]
        price = float(t["lastPrice"])
        prev = float(t["prevPrice24h"])
        return {
            "price": price,
            "open": prev,
            "high": float(t["highPrice24h"]),
            "low": float(t["lowPrice24h"]),
            "change": ((price - prev) / prev) * 100 if prev else 0,
            "volume": float(t["turnover24h"]) / 1e9,
        }
    except Exception as e:
        print(f"[24h] bybit failed: {e}", flush=True)
    return None


def fetch_1m_candles(since_ms: int, limit: int = 500) -> list:
    """Fetch 1m candles as [(high, low, close_time), ...]. For hit detection."""
    endpoints = [
        f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={since_ms}&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={since_ms}&limit={limit}",
    ]
    for url in endpoints:
        try:
            data = json.loads(_urlopen(url, timeout=10).read())
            return [(float(c[2]), float(c[3]), int(c[6])) for c in data]
        except Exception as e:
            print(f"[1m] {url.split('/')[2]} failed: {e}", flush=True)
    try:
        ex = _BybitPublicAPI()
        rows = ex.fetch_ohlcv("BTCUSDT", "1m", since=since_ms, limit=limit)
        return [(r[2], r[3], r[0] + 60000) for r in rows]
    except Exception as e:
        print(f"[1m] bybit-raw failed: {e}", flush=True)
    return []
