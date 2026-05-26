#!/usr/bin/env python3
"""
V+M Pattern — BTCUSDT Perpetual 15m + 1m
V         = Sharp drop + V-shaped reversal
M กลับหัว = Bounce → Higher Low (W) → 1m mini-AMD at neckline → LONG
M ซ้อน M  = 15m V+M structure ซ้อนด้วย 1m mini-AMD ที่ neckline

Entry  : 1m D close เกิน A ceiling ใกล้ neckline
SL     : ใต้ 1m M wick (จุดกลับตัวล่าสุด) − buffer
TP     : neckline + fib_leg × [3.5, 6.0, 8.0]   ← AMD style
         fib_leg = neckline − w_low

run    : python3 vm_backtest.py          → backtest
         python3 vm_backtest.py live     → เช็ควันนี้
"""

import os
import sys
import time
import pandas as pd
from datetime import datetime, timedelta, timezone
import warnings
warnings.filterwarnings('ignore')

from exchange_utils import make_exchange

# ─── CONFIG ──────────────────────────────────────────────────────────────────
SYMBOL       = 'BTC/USDT:USDT'
DAYS_BACK    = 90

SWING_N      = 3      # candles each side สำหรับ swing detection
MIN_DROP     = 0.015  # V left side: drop อย่างน้อย 1.5%
MIN_RECOVERY = 0.30   # V bounce ต้อง recover ≥ 30% ของ V height
MIN_HL_GAP   = 0.002  # W low ต้องสูงกว่า V low ≥ 0.2%

ZONE_WIDTH   = 120    # ±$ รอบ neckline สำหรับ 1m zone
SL_BUFFER    = 10     # $ ใต้ 1m M wick

RSI_PERIOD   = 14
USE_DIV      = False
USE_TREND    = False  # EMA200 uptrend filter (False = ปิด)
EMA_PERIOD   = 200

TP_RATIOS    = [3.5, 6.0, 8.0]   # AMD style: neckline + fib_leg × ratio

CACHE_FILE   = os.path.expanduser('~/Documents/.cache_1m_btcusdt.pkl')
CACHE_TTL_H  = 4      # โหลด cache ถ้าอายุ < 4 ชั่วโมง
MAX_RETRIES  = 3      # API retry attempts
# ─────────────────────────────────────────────────────────────────────────────

_ex, SYMBOL = make_exchange()


# ─── DATA FETCH + CACHE ───────────────────────────────────────────────────────

def _fetch_raw(tf: str, since_ms: int) -> pd.DataFrame:
    rows, ts = [], since_ms
    while True:
        batch = _ex.fetch_ohlcv(SYMBOL, tf, since=ts, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        ts = batch[-1][0] + 1
    if not rows:
        return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
    df = pd.DataFrame(rows, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df = df.set_index('ts').sort_index()
    return df[~df.index.duplicated()]


def fetch(tf: str, since_ms: int) -> pd.DataFrame:
    for attempt in range(MAX_RETRIES):
        try:
            return _fetch_raw(tf, since_ms)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = (attempt + 1) * 15
                print(f'  API error: {e}  — retry {attempt+2}/{MAX_RETRIES} in {wait}s')
                time.sleep(wait)
            else:
                raise RuntimeError(f'Failed after {MAX_RETRIES} attempts: {e}')


def fetch_1m(since_ms: int) -> pd.DataFrame:
    """ดึง 1m data พร้อม cache (โหลดจากไฟล์ถ้ายังไม่เก่า)"""
    since_ts = pd.Timestamp(since_ms, unit='ms', tz='UTC')

    if os.path.exists(CACHE_FILE):
        age_h = (time.time() - os.path.getmtime(CACHE_FILE)) / 3600
        if age_h < CACHE_TTL_H:
            try:
                cached = pd.read_pickle(CACHE_FILE)
                if not cached.empty and cached.index.min() <= since_ts:
                    print(f'  1m: loaded from cache (age {age_h:.1f}h, {len(cached):,} candles)')
                    return cached[cached.index >= since_ts]
            except Exception:
                pass   # cache corrupt → fetch fresh

    print(f'  1m: fetching {DAYS_BACK}d from Binance  ~2-3 min...')
    df = fetch('1m', since_ms)
    try:
        df.to_pickle(CACHE_FILE)
        print(f'  1m: {len(df):,} candles  (cached)')
    except Exception as e:
        print(f'  1m: {len(df):,} candles  (cache write failed: {e})')
    return df


# ─── INDICATORS ──────────────────────────────────────────────────────────────

def calc_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, float('inf'))
    return (100 - (100 / (1 + rs))).fillna(50)


def calc_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


# ─── SWING DETECTION ─────────────────────────────────────────────────────────

def swing_lows(df: pd.DataFrame, n: int = SWING_N) -> list:
    result = []
    for i in range(n, len(df) - n):
        lo = df['low'].iloc[i]
        if all(lo < df['low'].iloc[i-n:i]) and all(lo < df['low'].iloc[i+1:i+n+1]):
            result.append((df.index[i], lo))
    return result


def swing_highs(df: pd.DataFrame, n: int = SWING_N) -> list:
    result = []
    for i in range(n, len(df) - n):
        hi = df['high'].iloc[i]
        if all(hi > df['high'].iloc[i-n:i]) and all(hi > df['high'].iloc[i+1:i+n+1]):
            result.append((df.index[i], hi))
    return result


# ─── 1m MINI-AMD AT NECKLINE (M ซ้อน M) ─────────────────────────────────────

def entry_long_1m(df1m: pd.DataFrame, neckline: float):
    """
    Zone  = neckline ± ZONE_WIDTH
    M     = lowest wick ใน zone  (stop hunt ลง → SL anchor)
    D     = close เกิน A ceiling หลัง M → Entry LONG
    """
    zone_lo = neckline - ZONE_WIDTH
    zone_hi = neckline + 50

    in_zone = df1m[(df1m['high'] >= zone_lo) & (df1m['low'] <= zone_hi)]
    if len(in_zone) < 3:
        return None

    m_wick = in_zone['low'].min()
    m_idx  = in_zone['low'].idxmin()

    pre_m  = in_zone[in_zone.index <= m_idx]
    if pre_m.empty:
        return None
    a_ceil = pre_m['high'].quantile(0.75)

    after_m = df1m[df1m.index > m_idx]
    for idx, c in after_m.iterrows():
        if c['close'] > a_ceil:
            return {
                'entry_time': idx,
                'entry':      c['close'],
                'sl':         round(m_wick - SL_BUFFER, 2),
                'm_wick':     round(m_wick, 2),
            }
    return None


# ─── SIGNAL DETECTION ────────────────────────────────────────────────────────

def detect_signals(df15: pd.DataFrame, df1m: pd.DataFrame) -> list:
    df = df15.copy()
    df['rsi'] = calc_rsi(df['close'])
    if USE_TREND:
        df['ema'] = calc_ema(df['close'], EMA_PERIOD)

    s_lows  = swing_lows(df)
    s_highs = swing_highs(df)
    signals = []
    used_w  = set()

    for v_idx, v_low in s_lows:

        # ① V drop: prior swing high → ตรวจขนาด drop
        prior_hi = [(idx, hi) for idx, hi in s_highs if idx < v_idx]
        if not prior_hi:
            continue
        ref_idx, ref_hi = prior_hi[-1]
        drop = (ref_hi - v_low) / ref_hi
        if drop < MIN_DROP:
            continue

        # ② Neckline = swing high แรกหลัง V
        next_hi = [(idx, hi) for idx, hi in s_highs if idx > v_idx]
        if not next_hi:
            continue
        neck_idx, neckline = next_hi[0]

        v_height = neckline - v_low
        if v_height <= 0:
            continue
        if v_height / (ref_hi - v_low) < MIN_RECOVERY:
            continue

        # ③ W second bottom (Higher Low)
        next_lo = [(idx, lo) for idx, lo in s_lows if idx > neck_idx]
        if not next_lo:
            continue
        w_idx, w_low = next_lo[0]

        if w_low <= v_low * (1 + MIN_HL_GAP):   # ต้องเป็น Higher Low
            continue
        if w_low >= neckline:                     # ต้องอยู่ใต้ neckline
            continue
        if w_idx in used_w:
            continue

        # ④ EMA trend filter (optional)
        if USE_TREND and w_low < df.loc[w_idx, 'ema']:
            continue

        # ⑤ RSI Bullish Divergence
        if USE_DIV:
            rsi_v = df.loc[v_idx, 'rsi']
            rsi_w = df.loc[w_idx, 'rsi']
            if rsi_w <= rsi_v:
                continue

        # ⑥ 1m mini-AMD ที่ neckline (M ซ้อน M)
        w1m = df1m[
            (df1m.index >= w_idx) &
            (df1m.index <= w_idx + pd.Timedelta(hours=8))
        ]
        e = entry_long_1m(w1m, neckline)
        if e is None:
            continue

        # ⑦ SL / TP  (AMD style: neckline + fib_leg × ratio)
        fib_leg  = round(neckline - w_low, 2)
        entry    = round(e['entry'], 2)
        sl       = e['sl']
        risk     = round(entry - sl, 2)

        if risk <= 0 or fib_leg <= 0:
            continue
        if entry <= sl:         # entry ต้องสูงกว่า SL
            continue
        if entry > neckline + ZONE_WIDTH * 2:   # entry ไม่ควรไกลจาก neckline มาก
            continue

        tps = [round(neckline + fib_leg * r, 2) for r in TP_RATIOS]

        if tps[0] <= entry:     # TP1 ต้องสูงกว่า entry
            continue

        used_w.add(w_idx)

        signals.append({
            'v_idx':      v_idx,
            'v_low':      round(v_low, 2),
            'neckline':   round(neckline, 2),
            'w_idx':      w_idx,
            'w_low':      round(w_low, 2),
            'fib_leg':    fib_leg,
            'v_height':   round(v_height, 2),
            'entry_time': e['entry_time'],
            'entry':      entry,
            'sl':         sl,
            'risk':       risk,
            'tp1':        tps[0],
            'tp2':        tps[1],
            'tp3':        tps[2],
            'direction':  'LONG',
        })

    return signals


# ─── BACKTEST ────────────────────────────────────────────────────────────────

def backtest(df1m: pd.DataFrame, signals: list) -> pd.DataFrame:
    rows = []
    for sig in signals:
        future    = df1m[df1m.index > sig['entry_time']]
        tp_status = {'tp1': 'OPEN', 'tp2': 'OPEN', 'tp3': 'OPEN'}
        final     = 'OPEN'
        tp1_hit   = False

        for _, c in future.iterrows():
            for key, val in [('tp1', sig['tp1']), ('tp2', sig['tp2']), ('tp3', sig['tp3'])]:
                if tp_status[key] == 'OPEN' and c['high'] >= val:
                    tp_status[key] = 'WIN'
                    final = 'WIN'
                    if key == 'tp1':
                        tp1_hit = True

            if c['low'] <= sig['sl']:
                for k, v in tp_status.items():
                    if v == 'OPEN':
                        tp_status[k] = 'LOSS'
                if not tp1_hit:
                    final = 'LOSS'
                break

            if all(v != 'OPEN' for v in tp_status.values()):
                break

        rows.append({
            **sig,
            'outcome':    final,
            'tp1_status': tp_status['tp1'],
            'tp2_status': tp_status['tp2'],
            'tp3_status': tp_status['tp3'],
        })
    return pd.DataFrame(rows)


# ─── SUMMARY ─────────────────────────────────────────────────────────────────

def print_summary(df: pd.DataFrame):
    closed = df[df['outcome'] != 'OPEN']
    if closed.empty:
        print('No closed trades.')
        return

    total = len(closed)
    wins  = len(closed[closed['outcome'] == 'WIN'])
    bar   = '=' * 54

    print(f'\n{bar}')
    print(f'  V+M STRATEGY  |  BTCUSDT Perp  |  15m + 1m')
    print(bar)
    print(f'  Period    : {df["entry_time"].min().date()} → {df["entry_time"].max().date()}')
    print(f'  Signals   : {len(df)}  (closed {total})')
    print(f'  Win Rate  : {wins/total*100:.1f}%  ({wins}W / {total-wins}L)')
    print(f'  Avg Risk  : ${closed["risk"].mean():,.0f}')
    print(f'  Avg fib_leg: ${closed["fib_leg"].mean():,.0f}')
    print(bar)

    for col, label, ratio in [
        ('tp1_status', 'TP1  350%', 3.5),
        ('tp2_status', 'TP2  600%', 6.0),
        ('tp3_status', 'TP3  800%', 8.0),
    ]:
        hit = len(closed[closed[col] == 'WIN'])
        tot = len(closed[closed[col] != 'OPEN'])
        avg_rr = ratio * closed['fib_leg'].mean() / closed['risk'].mean() if closed['risk'].mean() > 0 else 0
        if tot:
            print(f'  {label} : {hit:3d}/{tot:3d} ({hit/tot*100:.0f}%)  avg RR ~{avg_rr:.1f}x')

    print(bar)
    print(f'  RSI div filter: {"ON" if USE_DIV else "OFF"}  |  '
          f'Trend filter: {"ON (EMA"+str(EMA_PERIOD)+")" if USE_TREND else "OFF"}')
    print(bar)


# ─── LIVE CHECK ───────────────────────────────────────────────────────────────

def live_check():
    now      = datetime.now(timezone.utc)
    since_ms = int((now - timedelta(days=14)).timestamp() * 1000)   # 14 วันล่าสุด

    print(f'\nV+M LIVE CHECK  |  {now.strftime("%Y-%m-%d %H:%M")} UTC')
    print('─' * 48)

    df15 = fetch('15m', since_ms)
    df1m = fetch_1m(since_ms)

    if df15.empty or df1m.empty:
        print('  ไม่สามารถดึงข้อมูลได้')
        return

    sigs = detect_signals(df15, df1m)
    now_price = df1m['close'].iloc[-1]
    print(f'  Current price : ${now_price:,.2f}\n')

    if not sigs:
        print('  ไม่มี V+M setup ใน 14 วันล่าสุด')
        return

    sig = sigs[-1]

    # เช็คสถานะ trade ล่าสุด
    future = df1m[df1m.index > sig['entry_time']]
    status = 'ACTIVE'
    for _, c in future.iterrows():
        if c['high'] >= sig['tp1']:
            status = 'TP1+ HIT'
            break
        if c['low'] <= sig['sl']:
            status = 'STOPPED'
            break

    icon = {'ACTIVE': '⏳', 'TP1+ HIT': '✅', 'STOPPED': '❌'}.get(status, '')
    print(f'  Status   : {icon} {status}')
    print(f'  V bottom : ${sig["v_low"]:,.2f}')
    print(f'  Neckline : ${sig["neckline"]:,.2f}')
    print(f'  W low    : ${sig["w_low"]:,.2f}  (Higher Low)')
    print(f'  fib_leg  : ${sig["fib_leg"]:,.2f}')
    print('─' * 48)
    print(f'  Entry    : ${sig["entry"]:,.2f}  ({sig["entry_time"].strftime("%m/%d %H:%M")} UTC)')
    print(f'  SL       : ${sig["sl"]:,.2f}  (risk ${sig["risk"]:,.0f})')
    print(f'  TP1 350% : ${sig["tp1"]:,.2f}  (RR ~{(sig["tp1"]-sig["entry"])/sig["risk"]:.1f}x)')
    print(f'  TP2 600% : ${sig["tp2"]:,.2f}  (RR ~{(sig["tp2"]-sig["entry"])/sig["risk"]:.1f}x)')
    print(f'  TP3 800% : ${sig["tp3"]:,.2f}  (RR ~{(sig["tp3"]-sig["entry"])/sig["risk"]:.1f}x)')
    print('─' * 48)


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'live':
        live_check()
        sys.exit(0)

    since_ms = int((datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).timestamp() * 1000)

    print(f'Fetching 15m ({DAYS_BACK}d)...')
    df15 = fetch('15m', since_ms)
    print(f'  {len(df15):,} candles')

    df1m = fetch_1m(since_ms)

    if df15.empty or df1m.empty:
        print('No data fetched. Check API connection.')
        sys.exit(1)

    sigs = detect_signals(df15, df1m)
    print(f'\nSignals found : {len(sigs)}')

    if sigs:
        results = backtest(df1m, sigs)
        print_summary(results)
        results.to_csv('vm_results.csv', index=False)
        print('\nSaved → vm_results.csv')
    else:
        print('No signals found. Try lowering MIN_DROP or DAYS_BACK.')
