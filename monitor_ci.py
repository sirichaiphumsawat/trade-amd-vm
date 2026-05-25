#!/usr/bin/env python3
"""
monitor_ci.py — Single-run trade monitor for GitHub Actions

Polls AMD + V+M once. Sends Telegram alert ONLY if:
  - Script outputs full setup signal
  - fib_leg >= FIB_LEG_MIN ($150)
  - Signal is fresh (entry fired < STALE_AFTER_MIN ago)
  - Signature not seen before (dedup via monitor_state.json)

Designed to run via cron */5min. Exits after one check.
"""

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE         = Path(__file__).resolve().parent
AMD_SCRIPT   = HERE / "amd_full.py"
VM_SCRIPT    = HERE / "vm_backtest.py"
STATE_FILE   = HERE / "monitor_state.json"
LOG_FILE     = HERE / "alerts_log.json"
ACTIVE_FILE  = HERE / "active_trades.json"
LOG_KEEP_DAYS = 90    # trim entries older than this
TRADE_EXPIRE_HOURS = 24   # drop active trade if no hit in this window

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─── USER RULES (per Trade.md) ───────────────────────────────────────────────
FIB_LEG_MIN     = 120     # USD — skip thin setups (lowered from 150 after missing
                          # 24 พค V+M LONG @ $76,702 fib_leg $138 which hit TP1+TP2+TP3)
STALE_AFTER_MIN = 30      # min — skip if entry fired > 30 min ago (no chasing)
TH_OFFSET       = timedelta(hours=7)

# Backtest win rates (90d, per strategy + direction)
WR_TABLE = {
    "AMD-SHORT": 14.0,
    "AMD-LONG":  44.0,
    "VM-LONG":   27.6,
}


# ─── TELEGRAM ────────────────────────────────────────────────────────────────
def telegram_send(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing")
        return False
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as r:
            resp = json.loads(r.read())
            if not resp.get("ok"):
                print(f"Telegram API error: {resp}")
                return False
            return True
    except Exception as e:
        print(f"Telegram send error: {e}")
        return False


def telegram_send_photo(photo_path: str, caption: str) -> bool:
    """Send photo with caption via multipart/form-data POST."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing")
        return False
    if not os.path.exists(photo_path):
        print(f"ERROR: photo not found: {photo_path}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    boundary = "----TgBoundary" + datetime.now().strftime("%Y%m%d%H%M%S%f")
    crlf = b"\r\n"

    with open(photo_path, "rb") as f:
        photo_bytes = f.read()

    parts = []
    # chat_id
    parts.append(f"--{boundary}".encode())
    parts.append(b'Content-Disposition: form-data; name="chat_id"')
    parts.append(b"")
    parts.append(TELEGRAM_CHAT.encode())
    # caption
    parts.append(f"--{boundary}".encode())
    parts.append(b'Content-Disposition: form-data; name="caption"')
    parts.append(b"")
    parts.append(caption.encode("utf-8"))
    # parse_mode
    parts.append(f"--{boundary}".encode())
    parts.append(b'Content-Disposition: form-data; name="parse_mode"')
    parts.append(b"")
    parts.append(b"Markdown")
    # photo
    parts.append(f"--{boundary}".encode())
    parts.append(b'Content-Disposition: form-data; name="photo"; filename="chart.png"')
    parts.append(b"Content-Type: image/png")
    parts.append(b"")
    parts.append(photo_bytes)
    parts.append(f"--{boundary}--".encode())
    parts.append(b"")

    body = crlf.join(parts)
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
            if not resp.get("ok"):
                print(f"Telegram sendPhoto error: {resp}")
                return False
            return True
    except Exception as e:
        print(f"Telegram photo send error: {e}")
        return False


# ─── HELPERS ─────────────────────────────────────────────────────────────────
def _clean_num(s: str) -> float:
    return float(s.replace(",", "").replace("$", ""))


def _now_utc_th() -> str:
    """Return '15:34 UTC (22:34 ไทย)' formatted string"""
    now = datetime.now(timezone.utc)
    th  = now + TH_OFFSET
    return f"{now.strftime('%H:%M')} UTC ({th.strftime('%H:%M')} ไทย)"


def _compute_rr(entry: float, sl: float, tp: float, direction: str) -> float:
    """Compute risk-reward ratio for entry/SL/TP"""
    risk   = abs(entry - sl)
    if risk == 0:
        return 0.0
    reward = abs(tp - entry)
    return reward / risk


def _parse_vm_entry_time(ts: str):
    """Parse 'MM/DD HH:MM UTC' to datetime (current year, UTC)"""
    try:
        # ts like "05/23 13:00 UTC"
        ts_clean = ts.replace("UTC", "").strip()
        m = re.match(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})", ts_clean)
        if not m:
            return None
        mm, dd, hh, mi = map(int, m.groups())
        now = datetime.now(timezone.utc)
        candidate = datetime(now.year, mm, dd, hh, mi, tzinfo=timezone.utc)
        # If candidate is in the future (year wrap), use previous year
        if candidate > now + timedelta(days=1):
            candidate = candidate.replace(year=now.year - 1)
        return candidate
    except Exception:
        return None


# ─── STATE ───────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def load_log() -> list:
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text())
        except Exception:
            pass
    return []


def append_log(entry: dict):
    """Append alert entry to alerts_log.json + trim old entries."""
    log = load_log()
    log.append(entry)

    # Trim entries older than LOG_KEEP_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOG_KEEP_DAYS)
    fresh = []
    for e in log:
        try:
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
            if ts >= cutoff:
                fresh.append(e)
        except Exception:
            fresh.append(e)   # keep if we can't parse (don't lose data)

    LOG_FILE.write_text(json.dumps(fresh, indent=2, ensure_ascii=False))


def make_log_entry(strategy: str, data: dict) -> dict:
    """Build alert log entry from check_amd/check_vm output."""
    return {
        "ts":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy":  strategy,             # "AMD" or "VM"
        "direction": data.get("direction", "?"),
        "entry":     data.get("entry"),
        "sl":        data.get("sl"),
        "tp1":       data.get("tp1"),
        "tp2":       data.get("tp2"),
        "tp3":       data.get("tp3"),
        "fib_leg":   data.get("fib_leg"),
        "signature": data.get("signature"),
    }


# ─── ACTIVE TRADES (for SL/TP hit detection) ─────────────────────────────────
def load_active() -> list:
    if ACTIVE_FILE.exists():
        try:
            return json.loads(ACTIVE_FILE.read_text())
        except Exception:
            pass
    return []


def save_active(active: list):
    ACTIVE_FILE.write_text(json.dumps(active, indent=2, ensure_ascii=False))


def add_active(strategy: str, data: dict):
    """Add a fresh alert to active_trades for SL/TP tracking."""
    active = load_active()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    active.append({
        "signature":  data.get("signature"),
        "strategy":   strategy,            # "AMD" or "VM"
        "direction":  data.get("direction", "?"),
        "entry":      data.get("entry"),
        "sl":         data.get("sl"),
        "tp1":        data.get("tp1"),
        "tp2":        data.get("tp2"),
        "tp3":        data.get("tp3"),
        "sent_at":    now_iso,
        "last_check": now_iso,
        "tp1_hit":    False,
        "tp2_hit":    False,
        "tp3_hit":    False,
        "sl_hit":     False,
    })
    save_active(active)


def fetch_1m_range(since_ms: int):
    """Fetch 1m BTC candles since timestamp. Returns list of (high, low, close_time).

    GH Actions runner IPs are geo-blocked from fapi.binance.com (futures, HTTP 451).
    Spot API api.binance.com works fine and gives essentially identical high/low
    for 1m candles (spot ≈ perp within a few dollars, irrelevant for $50+ TP hits).

    Tries spot first; falls back to multiple endpoints if blocked.
    """
    endpoints = [
        f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={since_ms}&limit=500",
        f"https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={since_ms}&limit=500",
    ]
    for url in endpoints:
        try:
            data = json.loads(urllib.request.urlopen(url, timeout=10).read())
            return [(float(c[2]), float(c[3]), int(c[6])) for c in data]
        except Exception as e:
            print(f"1m fetch error ({url.split('?')[0]}): {e}")
            continue
    return []


# ─── HIT DETECTION ───────────────────────────────────────────────────────────
def check_hits():
    """Scan active trades for SL/TP hits. Send alerts + update state."""
    active = load_active()
    if not active:
        return

    now = datetime.now(timezone.utc)
    survivors = []
    sent_count = 0

    for trade in active:
        # Expire stale trades (no hit in TRADE_EXPIRE_HOURS)
        sent_at = datetime.fromisoformat(trade["sent_at"].replace("Z", "+00:00"))
        age_h = (now - sent_at).total_seconds() / 3600
        if age_h > TRADE_EXPIRE_HOURS:
            print(f"Expire trade: {trade['signature']} (age {age_h:.1f}h)")
            continue

        last_check = datetime.fromisoformat(trade["last_check"].replace("Z", "+00:00"))
        since_ms = int(last_check.timestamp() * 1000) + 1   # +1ms to avoid re-checking same candle

        candles = fetch_1m_range(since_ms)
        if not candles:
            survivors.append(trade)
            continue

        period_high = max(c[0] for c in candles)
        period_low  = min(c[1] for c in candles)

        direction = trade["direction"]
        is_short = direction == "SHORT"

        # Determine which levels were hit this period
        hits = []

        # SL hit: SHORT → high >= sl ;  LONG → low <= sl
        if not trade["sl_hit"]:
            sl_triggered = (period_high >= trade["sl"]) if is_short else (period_low <= trade["sl"])
            if sl_triggered:
                trade["sl_hit"] = True
                hits.append(("SL", trade["sl"]))

        # TPs: SHORT → low <= tp ;  LONG → high >= tp
        for tp_key, tp_label in [("tp1", "TP1"), ("tp2", "TP2"), ("tp3", "TP3")]:
            hit_flag = f"{tp_key}_hit"
            if not trade[hit_flag]:
                tp_price = trade[tp_key]
                tp_triggered = (period_low <= tp_price) if is_short else (period_high >= tp_price)
                if tp_triggered:
                    trade[hit_flag] = True
                    hits.append((tp_label, tp_price))

        # Send alert per hit
        for label, price in hits:
            msg = format_hit_alert(trade, label, price)
            if telegram_send(msg):
                sent_count += 1
                print(f"Hit alert sent: {trade['signature']} {label}")
            else:
                print(f"Hit alert FAILED: {trade['signature']} {label}")

        # Update last_check; keep trade if not fully resolved
        trade["last_check"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        fully_resolved = trade["sl_hit"] or trade["tp3_hit"]
        if not fully_resolved:
            survivors.append(trade)
        else:
            print(f"Trade resolved: {trade['signature']}")

    save_active(survivors)
    if sent_count:
        print(f"Sent {sent_count} hit alert(s)")


def format_hit_alert(trade: dict, label: str, hit_price: float) -> str:
    """Build Telegram message for SL or TP hit."""
    entry = trade["entry"]
    direction = trade["direction"]
    strat = trade["strategy"]
    is_short = direction == "SHORT"
    is_sl = label == "SL"

    pnl = (entry - hit_price) if is_short else (hit_price - entry)
    pnl_pct = (pnl / entry) * 100

    risk = abs(entry - trade["sl"])
    reward = abs(hit_price - entry)
    rr = reward / risk if risk > 0 else 0
    rr_sign = "-" if is_sl else "+"

    if is_sl:
        header = f"❌ *SL HIT* — {strat} {direction}"
        result = "Trade closed (loss)"
    else:
        # Show what's left
        remaining = []
        for tp_key, tp_label in [("tp1", "TP1"), ("tp2", "TP2"), ("tp3", "TP3")]:
            if not trade[f"{tp_key}_hit"]:
                remaining.append(f"{tp_label} ${trade[tp_key]:,.0f}")
        if remaining:
            result = f"Active: {' · '.join(remaining)}"
        else:
            result = "🎯 *TP3 HIT — Trade complete*"
        header = f"✅ *{label} HIT* — {strat} {direction}"

    time_line = _now_utc_th()
    body = (
        f"Hit     ${hit_price:,.0f}\n"
        f"Entry   ${entry:,.0f}\n"
        f"P&L     {'+' if pnl >= 0 else ''}{pnl:,.0f}  ({'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%)\n"
        f"RR      {rr_sign}1:{rr:.1f}"
    )

    return (
        f"{header}\n"
        f"BTCUSDT · {time_line}\n\n"
        f"```\n{body}\n```\n"
        f"{result}"
    )


# ─── CHECKERS ────────────────────────────────────────────────────────────────
def check_amd():
    try:
        result = subprocess.run(
            ["python3", str(AMD_SCRIPT), "live"],
            capture_output=True, text=True, timeout=90,
        )
        out = result.stdout
        # Surface subprocess failures — previously silently hidden
        if result.returncode != 0 or "451" in result.stderr or "Error" in result.stderr:
            print(f"AMD subprocess rc={result.returncode}")
            if result.stderr:
                print(f"AMD stderr: {result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        print("AMD check timeout")
        return None

    if "Entry" not in out:
        # Print last few lines of output for diagnosis
        tail = out.strip().split("\n")[-3:] if out.strip() else ["(empty stdout)"]
        print(f"AMD: no Entry in output — tail: {' | '.join(tail)}")
        return None

    direction = re.search(r"Direction\s*:\s*(\w+)", out)
    m_ext     = re.search(r"M extreme\s*:\s*\$?([\d,]+\.?\d*)", out)
    entry     = re.search(r"Entry\s*:\s*\$?([\d,]+\.?\d*)", out)
    sl        = re.search(r"SL\s*:\s*\$?([\d,]+\.?\d*)", out)
    fib_leg   = re.search(r"Fib leg\s*:\s*\$?([\d,]+\.?\d*)", out)
    tp1       = re.search(r"TP1 350%\s*:\s*\$?([\d,]+\.?\d*)", out)
    tp2       = re.search(r"TP2 600%\s*:\s*\$?([\d,]+\.?\d*)", out)
    tp3       = re.search(r"TP3 800%\s*:\s*\$?([\d,]+\.?\d*)", out)

    if not (entry and m_ext and sl and fib_leg and tp1 and tp2 and tp3):
        return None

    fib_val = _clean_num(fib_leg.group(1))
    if fib_val < FIB_LEG_MIN:
        print(f"AMD skip: fib_leg ${fib_val:.0f} < ${FIB_LEG_MIN}")
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "signature": f"AMD-{today}-{m_ext.group(1)}",
        "direction": direction.group(1).upper() if direction else "?",
        "entry":     _clean_num(entry.group(1)),
        "sl":        _clean_num(sl.group(1)),
        "fib_leg":   fib_val,
        "tp1":       _clean_num(tp1.group(1)),
        "tp2":       _clean_num(tp2.group(1)),
        "tp3":       _clean_num(tp3.group(1)),
    }


def check_vm():
    try:
        result = subprocess.run(
            ["python3", str(VM_SCRIPT), "live"],
            capture_output=True, text=True, timeout=360,
        )
        out = result.stdout
        if result.returncode != 0 or "451" in result.stderr or "Error" in result.stderr:
            print(f"V+M subprocess rc={result.returncode}")
            if result.stderr:
                print(f"V+M stderr: {result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        print("V+M check timeout")
        return None

    if "ACTIVE" not in out:
        tail = out.strip().split("\n")[-3:] if out.strip() else ["(empty stdout)"]
        print(f"V+M: no ACTIVE in output — tail: {' | '.join(tail)}")
        return None

    entry_match = re.search(
        r"Entry\s*:\s*\$?([\d,]+\.?\d*)\s*\(([^)]+)\)", out
    )
    sl_match  = re.search(r"SL\s*:\s*\$?([\d,]+\.?\d*)", out)
    tp1_match = re.search(r"TP1 350%\s*:\s*\$?([\d,]+\.?\d*)", out)
    tp2_match = re.search(r"TP2 600%\s*:\s*\$?([\d,]+\.?\d*)", out)
    tp3_match = re.search(r"TP3 800%\s*:\s*\$?([\d,]+\.?\d*)", out)
    fib_match = re.search(r"fib_leg\s*:\s*\$?([\d,]+\.?\d*)", out)

    # Structure data for chart (optional — chart will skip if missing)
    vlow_match = re.search(r"V bottom\s*:\s*\$?([\d,]+\.?\d*)", out)
    neck_match = re.search(r"Neckline\s*:\s*\$?([\d,]+\.?\d*)", out)
    wlow_match = re.search(r"W low\s*:\s*\$?([\d,]+\.?\d*)", out)

    if not (entry_match and sl_match and tp1_match and tp2_match and tp3_match and fib_match):
        return None

    fib_val = _clean_num(fib_match.group(1))
    if fib_val < FIB_LEG_MIN:
        print(f"V+M skip: fib_leg ${fib_val:.0f} < ${FIB_LEG_MIN}")
        return None

    entry_ts_str = entry_match.group(2).strip()
    entry_dt = _parse_vm_entry_time(entry_ts_str)
    if entry_dt is None:
        print(f"V+M skip: cannot parse entry time '{entry_ts_str}'")
        return None

    age_min = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 60
    if age_min > STALE_AFTER_MIN:
        print(f"V+M skip: entry fired {age_min:.0f} min ago (stale > {STALE_AFTER_MIN} min — chasing)")
        return None

    return {
        "signature": f"VM-{entry_ts_str}",
        "direction": "LONG",
        "entry":     _clean_num(entry_match.group(1)),
        "entry_ts":  entry_ts_str,
        "sl":        _clean_num(sl_match.group(1)),
        "fib_leg":   fib_val,
        "tp1":       _clean_num(tp1_match.group(1)),
        "tp2":       _clean_num(tp2_match.group(1)),
        "tp3":       _clean_num(tp3_match.group(1)),
        # Structure (for chart) — may be None if vm_backtest output changed
        "v_low":     _clean_num(vlow_match.group(1)) if vlow_match else None,
        "neckline":  _clean_num(neck_match.group(1)) if neck_match else None,
        "w_low":     _clean_num(wlow_match.group(1)) if wlow_match else None,
    }


# ─── ALERT FORMATTING ────────────────────────────────────────────────────────
def format_alert(strategy: str, data: dict) -> str:
    """Build Telegram Markdown message in Design C v2 style"""
    entry, sl  = data["entry"], data["sl"]
    tp1, tp2, tp3 = data["tp1"], data["tp2"], data["tp3"]
    direction  = data["direction"]
    is_short   = direction == "SHORT"

    arrow = "↓" if is_short else "↑"
    d1 = abs(tp1 - entry)
    d2 = abs(tp2 - entry)
    d3 = abs(tp3 - entry)
    rr1 = _compute_rr(entry, sl, tp1, direction)
    rr2 = _compute_rr(entry, sl, tp2, direction)
    rr3 = _compute_rr(entry, sl, tp3, direction)

    wr_key = f"{strategy}-{direction}"
    wr = WR_TABLE.get(wr_key, 0)

    if strategy == "AMD":
        header = f"🚨 *AMD {direction} — ready*"
        tag = "BTCUSDT 15m"
    else:
        header = "🚀 *V+M LONG — signal fired*"
        tag = "BTCUSDT"

    # Format WR: drop .0 for whole numbers (44%, not 44.0%)
    wr_str = f"{wr:.0f}%" if wr == int(wr) else f"{wr:.1f}%"

    body = (
        f"Entry   ${entry:,.0f}\n"
        f"SL      ${sl:,.0f}\n"
        f"─────────────────────────\n"
        f"TP1   ${tp1:,.0f}  {arrow}{d1:>5,.0f}  1:{rr1:.1f}\n"
        f"TP2   ${tp2:,.0f}  {arrow}{d2:>5,.0f}  1:{rr2:.1f}\n"
        f"TP3   ${tp3:,.0f}  {arrow}{d3:>5,.0f}  1:{rr3:.1f}\n"
        f"─────────────────────────\n"
        f"fib_leg ${data['fib_leg']:,.0f}   ✓ pass\n"
        f"WR 90d  {wr_str}  ({wr_key.replace('-', ' ')})"
    )

    time_line = _now_utc_th()
    return f"{header}\n{tag} · {time_line}\n\n```\n{body}\n```"


# ─── CHART ATTACHMENT ────────────────────────────────────────────────────────
def try_build_amd_chart():
    """Try to generate AMD chart for Telegram. Returns path or None."""
    try:
        import chart_setup
        path = chart_setup.build_amd_short_chart("/tmp/btc_amd_alert.png")
        if path and os.path.exists(path):
            print(f"AMD chart built: {path} ({os.path.getsize(path):,} bytes)")
            return path
    except Exception as e:
        print(f"AMD chart build failed (non-fatal): {e}")
    return None


def try_build_vm_chart(signal):
    """Try to generate VM chart for Telegram. Returns path or None."""
    try:
        import chart_setup
        path = chart_setup.build_vm_long_chart(signal, "/tmp/btc_vm_alert.png")
        if path and os.path.exists(path):
            print(f"VM chart built: {path} ({os.path.getsize(path):,} bytes)")
            return path
        print("VM chart skipped — missing structure data")
    except Exception as e:
        print(f"VM chart build failed (non-fatal): {e}")
    return None


def send_alert(text: str, chart_path=None) -> bool:
    """Send alert with chart if available, fall back to text."""
    if chart_path:
        # Telegram caption limit is 1024 chars — our format is ~500, safe
        if telegram_send_photo(chart_path, text):
            return True
        print("Photo send failed, falling back to text-only")
    return telegram_send(text)


# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    state = load_state()
    new_alerts = []

    # AMD — generate chart (SHORT only for now; LONG uses text)
    amd = check_amd()
    if amd and amd["signature"] != state.get("last_amd_sig"):
        msg = format_alert("AMD", amd)
        chart = try_build_amd_chart() if amd["direction"] == "SHORT" else None
        if send_alert(msg, chart):
            state["last_amd_sig"] = amd["signature"]
            append_log(make_log_entry("AMD", amd))
            add_active("AMD", amd)
            new_alerts.append(f"AMD {amd['direction']}{' +chart' if chart else ''}")

    # V+M — chart attached when structure data is available
    vm = check_vm()
    if vm and vm["signature"] != state.get("last_vm_sig"):
        msg = format_alert("VM", vm)
        chart = try_build_vm_chart(vm)
        if send_alert(msg, chart):
            state["last_vm_sig"] = vm["signature"]
            append_log(make_log_entry("VM", vm))
            add_active("VM", vm)
            new_alerts.append(f"V+M LONG{' +chart' if chart else ''}")

    if new_alerts:
        save_state(state)
        print(f"Sent alerts: {', '.join(new_alerts)}")
    else:
        print("No new setup (or filtered out)")

    # Scan active trades for SL/TP hits (independent of new alerts)
    check_hits()

    sys.exit(0)


if __name__ == "__main__":
    main()
