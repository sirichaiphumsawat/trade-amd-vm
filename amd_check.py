#!/usr/bin/env python3
"""
AMD Live Check — BTCUSDT Perpetual 15m
รันแล้วบอกสถานะ AMD วันนี้ทันที
"""

import ccxt
import pandas as pd
from datetime import datetime, timezone

SYMBOL      = 'BTC/USDT:USDT'
TIMEFRAME   = '15m'
REWARD_RISK = 2.0

ASIAN_START = 0
ASIAN_END   = 8
MANIP_END   = 17


def fetch_today() -> pd.DataFrame:
    exchange = ccxt.binanceusdm({'enableRateLimit': True})
    today_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    since_ms  = int(today_utc.timestamp() * 1000)

    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, since=since_ms, limit=200)
    df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df = df.set_index('ts').sort_index()
    return df


def check_amd(df: pd.DataFrame):
    now_hour = datetime.now(timezone.utc).hour
    now_price = df['close'].iloc[-1]

    asian = df[df.index.hour < ASIAN_END]
    post  = df[(df.index.hour >= ASIAN_END) & (df.index.hour < MANIP_END)]

    print(f"\n{'='*48}")
    print(f"  AMD CHECK  |  BTCUSDT 15m  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"{'='*48}")
    print(f"  Current price : ${now_price:,.2f}")

    # ── Phase 1: รอ Asian session ปิด ────────────────────
    if now_hour < ASIAN_END:
        remaining = ASIAN_END - now_hour
        a_high = asian['high'].max() if len(asian) > 0 else None
        a_low  = asian['low'].min()  if len(asian) > 0 else None
        print(f"\n  Phase : ACCUMULATION (รออีก ~{remaining}h)")
        if a_high:
            print(f"  Range so far : ${a_low:,.2f} – ${a_high:,.2f}  (${a_high-a_low:,.0f})")
        print(f"\n  → ยังไม่มี setup  รอ Asian session ปิด 08:00 UTC")
        return

    if len(asian) == 0:
        print("\n  ไม่มีข้อมูล Asian session วันนี้")
        return

    a_high = asian['high'].max()
    a_low  = asian['low'].min()
    a_range = a_high - a_low

    print(f"\n  Asian Range  : ${a_low:,.2f} – ${a_high:,.2f}  (${a_range:,.0f})")

    if a_range < 100:
        print("  → Asian range แคบเกิน ($100) ข้าม setup วันนี้")
        return

    # ── Phase 2: หา Manipulation ─────────────────────────
    manip_candle = None
    manip_dir    = None

    for idx, c in post.iterrows():
        if c['high'] > a_high:
            manip_candle = c
            manip_dir    = 'UP'
            manip_time   = idx
            break
        if c['low'] < a_low:
            manip_candle = c
            manip_dir    = 'DOWN'
            manip_time   = idx
            break

    if manip_candle is None:
        print(f"\n  Phase : WAITING FOR MANIPULATION")
        print(f"  Watch : break above ${a_high:,.2f}  or  below ${a_low:,.2f}")
        return

    # แสดง Manipulation ที่พบ
    if manip_dir == 'UP':
        manip_extreme = manip_candle['high']
        print(f"\n  Manipulation : UP  wick → ${manip_extreme:,.2f}  at {manip_time.strftime('%H:%M')} UTC")
        print(f"  Expect       : SHORT  (ราคาจะกลับลง)")
    else:
        manip_extreme = manip_candle['low']
        print(f"\n  Manipulation : DOWN  wick → ${manip_extreme:,.2f}  at {manip_time.strftime('%H:%M')} UTC")
        print(f"  Expect       : LONG  (ราคาจะกลับขึ้น)")

    # ── Phase 3: หา Entry (Distribution) ─────────────────
    after_manip = post[post.index > manip_time]
    entry_candle = None

    for idx, c in after_manip.iterrows():
        if manip_dir == 'UP' and c['close'] < a_high:
            entry_candle = c
            entry_time   = idx
            break
        if manip_dir == 'DOWN' and c['close'] > a_low:
            entry_candle = c
            entry_time   = idx
            break

    if entry_candle is None:
        print(f"\n  Phase : WAITING FOR ENTRY")
        if manip_dir == 'UP':
            print(f"  Watch : candle CLOSE กลับต่ำกว่า ${a_high:,.2f}")
        else:
            print(f"  Watch : candle CLOSE กลับสูงกว่า ${a_low:,.2f}")
        return

    # ── Setup พร้อมแล้ว ───────────────────────────────────
    entry = entry_candle['close']
    if manip_dir == 'UP':
        direction = 'SHORT'
        sl   = manip_extreme
        risk = sl - entry
        tp   = entry - risk * REWARD_RISK
    else:
        direction = 'LONG'
        sl   = manip_extreme
        risk = entry - sl
        tp   = entry + risk * REWARD_RISK

    # เช็คว่า trade ยัง active หรือ hit SL/TP แล้ว
    after_entry = post[post.index > entry_time]
    status = 'ACTIVE'
    for _, c in after_entry.iterrows():
        if direction == 'SHORT':
            if c['high'] >= sl:
                status = 'LOSS'
                break
            if c['low'] <= tp:
                status = 'WIN'
                break
        else:
            if c['low'] <= sl:
                status = 'LOSS'
                break
            if c['high'] >= tp:
                status = 'WIN'
                break

    status_icon = {'ACTIVE': '⏳ ACTIVE', 'WIN': '✅ WIN', 'LOSS': '❌ LOSS'}

    print(f"\n  {'─'*44}")
    print(f"  SETUP : {direction}  [{status_icon[status]}]")
    print(f"  Entry : ${entry:,.2f}  (at {entry_time.strftime('%H:%M')} UTC)")
    print(f"  SL    : ${sl:,.2f}  (risk ${risk:,.0f})")
    print(f"  TP    : ${tp:,.2f}  (reward ${risk*REWARD_RISK:,.0f})  RR 1:{REWARD_RISK}")
    if status == 'ACTIVE':
        print(f"\n  Current price ${now_price:,.2f}  →  {abs(now_price-entry):,.0f} pts from entry")
    print(f"  {'─'*44}\n")


if __name__ == '__main__':
    df = fetch_today()
    check_amd(df)
