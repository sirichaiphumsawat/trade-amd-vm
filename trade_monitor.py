#!/usr/bin/env python3
"""
trade_monitor.py — Background poller สำหรับ AMD + V+M setup

แจ้งเตือน macOS เฉพาะตอน setup ใหม่ (fully confirmed) เท่านั้น
ใช้ amd_full.py และ vm_backtest.py เป็น source of truth (subprocess)

Usage:
    python3 trade_monitor.py              # รัน foreground
    nohup python3 trade_monitor.py &      # background (ง่ายสุด)
"""

import subprocess
import re
import json
import time
import sys
from pathlib import Path
from datetime import datetime, timezone

HOME            = Path.home()
HERE            = Path(__file__).resolve().parent
AMD_SCRIPT      = HERE / "amd_full.py"
VM_SCRIPT       = HERE / "vm_backtest.py"
STATE_FILE      = HOME / ".trade_monitor_state.json"
LOG_FILE        = HERE / "trade_monitor.log"
POLL_SECONDS    = 300        # 5 minutes
AMD_TIMEOUT     = 60
VM_TIMEOUT      = 300        # vm fetches 90d 1m (cached after first run)


# ─── NOTIFICATION ────────────────────────────────────────────────────────────
def notify(title: str, message: str, subtitle: str = "", sound: str = "Glass"):
    """macOS notification via terminal-notifier (more reliable than osascript)"""
    cmd = ["terminal-notifier",
           "-title", title,
           "-message", message,
           "-sound", sound]
    if subtitle:
        cmd += ["-subtitle", subtitle]
    subprocess.run(cmd, check=False)


# ─── STATE ───────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    line = f"[{ts}] {msg}\n"
    with LOG_FILE.open("a") as f:
        f.write(line)
    print(line, end="", flush=True)


# ─── CHECKERS (parse output of existing scripts) ──────────────────────────────
def check_amd():
    """Return setup dict if AMD has fully confirmed signal, else None"""
    try:
        result = subprocess.run(
            ["python3", str(AMD_SCRIPT), "live"],
            capture_output=True, text=True, timeout=AMD_TIMEOUT,
        )
        out = result.stdout
    except subprocess.TimeoutExpired:
        log("AMD check timeout")
        return None

    # No setup → script prints "ยังไม่มี setup" or "Phase: ACCUMULATION"
    if "Entry" not in out:
        return None

    # Parse signal details
    direction = re.search(r"Direction\s*:\s*(\w+)", out)
    m_ext     = re.search(r"M extreme\s*:\s*\$?([\d,]+\.?\d*)", out)
    entry     = re.search(r"Entry\s*:\s*\$?([\d,]+\.?\d*)", out)
    fib_leg   = re.search(r"Fib leg\s*:\s*\$?([\d,]+\.?\d*)", out)
    tp1       = re.search(r"TP1 350%\s*:\s*\$?([\d,]+\.?\d*)", out)

    if not (entry and m_ext):
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    signature = f"AMD-{today}-{m_ext.group(1)}"

    return {
        "signature": signature,
        "direction": direction.group(1) if direction else "?",
        "entry":     entry.group(1),
        "fib_leg":   fib_leg.group(1) if fib_leg else "?",
        "tp1":       tp1.group(1) if tp1 else "?",
    }


def check_vm():
    """Return setup dict if V+M is ACTIVE (fresh), else None"""
    try:
        result = subprocess.run(
            ["python3", str(VM_SCRIPT), "live"],
            capture_output=True, text=True, timeout=VM_TIMEOUT,
        )
        out = result.stdout
    except subprocess.TimeoutExpired:
        log("V+M check timeout")
        return None

    if "ACTIVE" not in out:
        return None

    entry_match = re.search(
        r"Entry\s*:\s*\$?([\d,]+\.?\d*)\s*\(([^)]+)\)", out
    )
    sl_match   = re.search(r"SL\s*:\s*\$?([\d,]+\.?\d*)", out)
    tp1_match  = re.search(r"TP1 350%\s*:\s*\$?([\d,]+\.?\d*)", out)
    fib_match  = re.search(r"fib_leg\s*:\s*\$?([\d,]+\.?\d*)", out)

    if not entry_match:
        return None

    # Use entry timestamp as signature so we don't re-alert same fire
    signature = f"VM-{entry_match.group(2).strip()}"

    return {
        "signature": signature,
        "entry":     entry_match.group(1),
        "entry_ts":  entry_match.group(2).strip(),
        "sl":        sl_match.group(1) if sl_match else "?",
        "tp1":       tp1_match.group(1) if tp1_match else "?",
        "fib_leg":   fib_match.group(1) if fib_match else "?",
    }


# ─── MAIN LOOP ───────────────────────────────────────────────────────────────
def main():
    log("Monitor started")
    notify(
        title="Trade Monitor started",
        message="จะแจ้งเตือนเฉพาะตอนมี setup เท่านั้น",
        sound="Pop",
    )

    state = load_state()
    last_amd = state.get("last_amd_sig")
    last_vm  = state.get("last_vm_sig")

    while True:
        try:
            # AMD check
            amd = check_amd()
            if amd:
                if amd["signature"] != last_amd:
                    notify(
                        title=f"🚨 AMD {amd['direction']} — ready to enter",
                        subtitle=f"BTCUSDT 15m  |  fib_leg ${amd['fib_leg']} ✓",
                        message=f"Entry ${amd['entry']}   TP1 ${amd['tp1']}",
                        sound="Glass",
                    )
                    log(f"AMD alert: {amd['signature']}")
                    last_amd = amd["signature"]
                    state["last_amd_sig"] = last_amd
                    save_state(state)
            # V+M check
            vm = check_vm()
            if vm:
                if vm["signature"] != last_vm:
                    notify(
                        title="🚀 V+M LONG — signal fired",
                        subtitle=f"BTCUSDT  |  fib_leg ${vm['fib_leg']} ✓",
                        message=f"Entry ${vm['entry']}   SL ${vm['sl']}   TP1 ${vm['tp1']}",
                        sound="Funk",
                    )
                    log(f"V+M alert: {vm['signature']}")
                    last_vm = vm["signature"]
                    state["last_vm_sig"] = last_vm
                    save_state(state)

            if not amd and not vm:
                log("no setup")

            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            log("Monitor stopped (Ctrl+C)")
            break
        except Exception as e:
            log(f"Error: {e} — retry in 30s")
            time.sleep(30)


if __name__ == "__main__":
    main()
