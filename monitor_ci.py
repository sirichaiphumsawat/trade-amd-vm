#!/usr/bin/env python3
"""
monitor_ci.py — Single-run trade monitor for GitHub Actions

Polls AMD + V+M once, sends Telegram alert if new setup, updates state file.
Designed to run via cron (every 5 min). No loop — exit after one check.
"""

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE         = Path(__file__).resolve().parent
AMD_SCRIPT   = HERE / "amd_full.py"
VM_SCRIPT    = HERE / "vm_backtest.py"
STATE_FILE   = HERE / "monitor_state.json"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")


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
    fib_leg   = re.search(r"Fib leg\s*:\s*\$?([\d,]+\.?\d*)", out)
    tp1       = re.search(r"TP1 350%\s*:\s*\$?([\d,]+\.?\d*)", out)

    if not (entry and m_ext):
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "signature": f"AMD-{today}-{m_ext.group(1)}",
        "direction": direction.group(1) if direction else "?",
        "entry":     entry.group(1),
        "fib_leg":   fib_leg.group(1) if fib_leg else "?",
        "tp1":       tp1.group(1) if tp1 else "?",
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
    fib_match = re.search(r"fib_leg\s*:\s*\$?([\d,]+\.?\d*)", out)

    if not entry_match:
        return None

    return {
        "signature": f"VM-{entry_match.group(2).strip()}",
        "entry":     entry_match.group(1),
        "entry_ts":  entry_match.group(2).strip(),
        "sl":        sl_match.group(1) if sl_match else "?",
        "tp1":       tp1_match.group(1) if tp1_match else "?",
        "fib_leg":   fib_match.group(1) if fib_match else "?",
    }


# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    state = load_state()
    new_alerts = []

    # AMD
    amd = check_amd()
    if amd:
        if amd["signature"] != state.get("last_amd_sig"):
            msg = (
                f"🚨 *AMD {amd['direction']} setup*\n"
                f"_BTCUSDT 15m_  ·  fib\\_leg ${amd['fib_leg']}\n\n"
                f"Entry  `${amd['entry']}`\n"
                f"TP1    `${amd['tp1']}`  _(350%)_"
            )
            if telegram_send(msg):
                state["last_amd_sig"] = amd["signature"]
                new_alerts.append(f"AMD {amd['direction']}")

    # V+M
    vm = check_vm()
    if vm:
        if vm["signature"] != state.get("last_vm_sig"):
            msg = (
                f"🚀 *V+M LONG signal fired*\n"
                f"_BTCUSDT_  ·  fib\\_leg ${vm['fib_leg']}  ·  {vm['entry_ts']}\n\n"
                f"Entry  `${vm['entry']}`\n"
                f"SL     `${vm['sl']}`\n"
                f"TP1    `${vm['tp1']}`  _(350%)_"
            )
            if telegram_send(msg):
                state["last_vm_sig"] = vm["signature"]
                new_alerts.append("V+M LONG")

    if new_alerts:
        save_state(state)
        print(f"Sent alerts: {', '.join(new_alerts)}")
        sys.exit(0)
    else:
        print("No new setup")
        sys.exit(0)


if __name__ == "__main__":
    main()
