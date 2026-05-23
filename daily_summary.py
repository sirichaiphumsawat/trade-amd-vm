#!/usr/bin/env python3
"""
daily_summary.py — Send morning brief to Telegram (00:00 UTC = 07:00 ไทย)

Reads alerts_log.json + Binance 24h ticker, builds Thai-friendly summary.
Designed to run via GitHub Actions cron once per day.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE      = Path(__file__).resolve().parent
LOG_FILE  = HERE / "alerts_log.json"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")

TH_OFFSET = timedelta(hours=7)
THAI_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัส", "ศุกร์", "เสาร์", "อาทิตย์"]


# ─── DATA ────────────────────────────────────────────────────────────────────
def fetch_btc_24h():
    """Fetch BTCUSDT 24h ticker stats from Binance Futures."""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT"
    try:
        d = json.loads(urllib.request.urlopen(url, timeout=10).read())
        return {
            "price":   float(d["lastPrice"]),
            "open":    float(d["openPrice"]),
            "high":    float(d["highPrice"]),
            "low":     float(d["lowPrice"]),
            "change":  float(d["priceChangePercent"]),
            "volume":  float(d["quoteVolume"]) / 1e9,   # billions USDT
        }
    except Exception as e:
        print(f"Binance fetch error: {e}")
        return None


def load_alerts_24h():
    """Return alerts from last 24h."""
    if not LOG_FILE.exists():
        return []
    try:
        all_alerts = json.loads(LOG_FILE.read_text())
    except Exception:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    fresh = []
    for a in all_alerts:
        try:
            ts = datetime.fromisoformat(a["ts"].replace("Z", "+00:00"))
            if ts >= cutoff:
                fresh.append(a)
        except Exception:
            pass
    return fresh


# ─── FORMAT ──────────────────────────────────────────────────────────────────
def format_summary(price_data, alerts) -> str:
    now = datetime.now(timezone.utc)
    th  = now + TH_OFFSET
    day_th = THAI_DAYS[th.weekday()]
    date_str = th.strftime(f"{day_th} %d/%m/%Y")

    lines = [f"🌅 *Daily Brief — {date_str}*", ""]

    # BTC 24h section
    if price_data:
        p = price_data
        arrow = "🟢" if p["change"] >= 0 else "🔴"
        sign = "+" if p["change"] >= 0 else ""
        rng = p["high"] - p["low"]
        lines += [
            "📊 *BTC 24h*",
            "```",
            f"Open    ${p['open']:>10,.0f}",
            f"Close   ${p['price']:>10,.0f}  {sign}{p['change']:.2f}%  {arrow}",
            f"High    ${p['high']:>10,.0f}",
            f"Low     ${p['low']:>10,.0f}",
            f"Range   ${rng:>10,.0f}",
            f"Vol     ${p['volume']:>10,.1f}B",
            "```",
            "",
        ]
    else:
        lines += ["📊 *BTC 24h* — _ดึงข้อมูลไม่ได้_", ""]

    # Alerts section
    if alerts:
        lines.append(f"🚨 *Alerts ({len(alerts)} ส่ง)*")
        lines.append("```")
        for a in alerts:
            try:
                ts = datetime.fromisoformat(a["ts"].replace("Z", "+00:00"))
                th_time = (ts + TH_OFFSET).strftime("%H:%M")
            except Exception:
                th_time = "??:??"

            strat = a.get("strategy", "?")
            direction = a.get("direction", "?")
            entry = a.get("entry", 0) or 0
            fib   = a.get("fib_leg", 0) or 0

            icon = "🚨" if strat == "AMD" else "🚀"
            label = f"{strat} {direction}"
            lines.append(
                f"{th_time}  {icon} {label:<10}  ${entry:>8,.0f}  fib ${fib:>5,.0f}"
            )
        lines.append("```")
        lines.append("")
    else:
        lines += [
            "💤 *ไม่มี alert ใน 24 ชม. ที่ผ่านมา*",
            "_(ไม่มี setup ผ่าน filter)_",
            "",
        ]

    # Footer
    lines.append("💡 `/check` ตรวจตอนนี้  ·  `/price` ดูราคา")

    return "\n".join(lines)


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


# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    print("Fetching BTC 24h ticker...")
    price = fetch_btc_24h()
    if price:
        print(f"  Close ${price['price']:,.0f}  ({price['change']:+.2f}%)")

    print("Loading alerts from last 24h...")
    alerts = load_alerts_24h()
    print(f"  {len(alerts)} alerts found")

    text = format_summary(price, alerts)
    print("\n=== Summary ===")
    print(text)
    print("===============\n")

    if telegram_send(text):
        print("Sent ✓")
    else:
        print("Send failed ✗")
        sys.exit(1)


if __name__ == "__main__":
    main()
