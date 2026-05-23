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

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─── USER RULES (per Trade.md) ───────────────────────────────────────────────
FIB_LEG_MIN     = 150     # USD — skip thin setups
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


# ─── CHECKERS ────────────────────────────────────────────────────────────────
def check_amd():
    try:
        result = subprocess.run(
            ["python3", str(AMD_SCRIPT), "live"],
            capture_output=True, text=True, timeout=90,
        )
        out = result.stdout
    except subprocess.TimeoutExpired:
        print("AMD check timeout")
        return None

    if "Entry" not in out:
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
    except subprocess.TimeoutExpired:
        print("V+M check timeout")
        return None

    if "ACTIVE" not in out:
        return None

    entry_match = re.search(
        r"Entry\s*:\s*\$?([\d,]+\.?\d*)\s*\(([^)]+)\)", out
    )
    sl_match  = re.search(r"SL\s*:\s*\$?([\d,]+\.?\d*)", out)
    tp1_match = re.search(r"TP1 350%\s*:\s*\$?([\d,]+\.?\d*)", out)
    tp2_match = re.search(r"TP2 600%\s*:\s*\$?([\d,]+\.?\d*)", out)
    tp3_match = re.search(r"TP3 800%\s*:\s*\$?([\d,]+\.?\d*)", out)
    fib_match = re.search(r"fib_leg\s*:\s*\$?([\d,]+\.?\d*)", out)

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


# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    state = load_state()
    new_alerts = []

    # AMD
    amd = check_amd()
    if amd and amd["signature"] != state.get("last_amd_sig"):
        msg = format_alert("AMD", amd)
        if telegram_send(msg):
            state["last_amd_sig"] = amd["signature"]
            new_alerts.append(f"AMD {amd['direction']}")

    # V+M
    vm = check_vm()
    if vm and vm["signature"] != state.get("last_vm_sig"):
        msg = format_alert("VM", vm)
        if telegram_send(msg):
            state["last_vm_sig"] = vm["signature"]
            new_alerts.append("V+M LONG")

    if new_alerts:
        save_state(state)
        print(f"Sent alerts: {', '.join(new_alerts)}")
    else:
        print("No new setup (or filtered out)")
    sys.exit(0)


if __name__ == "__main__":
    main()
