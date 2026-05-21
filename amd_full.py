#!/usr/bin/env python3
"""
AMD Full Strategy Backtest — BTCUSDT Perpetual
15m : Asian Range → Manipulation → MSS → 50% Retrace
1m  : Mini-AMD at 50% zone → Entry
SL  : เหนือ 1m M wick + buffer
TP  : bounce_top − leg × [3.5, 6.0, 8.0]
"""

import os
import sys
import time
import ccxt
import pandas as pd
from datetime import datetime, timedelta, timezone
import warnings
warnings.filterwarnings('ignore')

# ─── CONFIG ──────────────────────────────────────────────────────────────────
SYMBOL      = 'BTC/USDT:USDT'
DAYS_BACK   = 90

ASIAN_END   = 8    # UTC: Asian session จบ
MANIP_END   = 17   # UTC: NY session จบ

MIN_RANGE   = 200  # Asian range ต่ำสุด ($)
LEG_CANDLES = 16   # จำนวน 15m candles หา MSS หลัง M
RETRACE_LO  = 0.35 # retrace ต่ำสุด 35%
RETRACE_HI  = 0.65 # retrace สูงสุด 65%
BOUNCE_LOOK = 24   # จำนวน 15m candles หา Bounce หลัง MSS

ZONE_WIDTH  = 80   # ±$ รอบ bounce top สำหรับ 1m zone
SL_BUFFER   = 10   # $ buffer เหนือ 1m M wick

TP_RATIOS   = [3.5, 6.0, 8.0]   # TP1, TP2, TP3

RSI_PERIOD  = 14   # RSI period
USE_DIV     = True # False = ปิด divergence filter ชั่วคราว

CACHE_FILE  = os.path.expanduser('~/Documents/.cache_1m_btcusdt.pkl')
CACHE_TTL_H = 4
MAX_RETRIES = 3
# ─────────────────────────────────────────────────────────────────────────────

_ex = ccxt.binanceusdm({'enableRateLimit': True})


# ─── DATA FETCH ──────────────────────────────────────────────────────────────

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
                raise


def fetch_1m(since_ms: int) -> pd.DataFrame:
    since_ts = pd.Timestamp(since_ms, unit='ms', tz='UTC')
    if os.path.exists(CACHE_FILE):
        age_h = (time.time() - os.path.getmtime(CACHE_FILE)) / 3600
        if age_h < CACHE_TTL_H:
            try:
                cached = pd.read_pickle(CACHE_FILE)
                if not cached.empty and cached.index.min() <= since_ts:
                    print(f'  1m: cache (age {age_h:.1f}h, {len(cached):,} candles)')
                    return cached[cached.index >= since_ts]
            except Exception:
                pass
    df = fetch('1m', since_ms)
    try:
        df.to_pickle(CACHE_FILE)
    except Exception:
        pass
    return df


# ─── RSI DIVERGENCE ──────────────────────────────────────────────────────────

def calc_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, float('inf'))
    return 100 - (100 / (1 + rs))


def _prev_swing_high(df15: pd.DataFrame, before_idx, lookback: int = 60, n: int = 3):
    """หา swing high ล่าสุดก่อน before_idx (n candles clearance แต่ละด้าน)"""
    w = df15[df15.index < before_idx].tail(lookback)
    if len(w) < 2 * n + 1:
        return None, None
    for i in range(len(w) - n - 1, n - 1, -1):
        hi = w['high'].iloc[i]
        if all(hi > w['high'].iloc[i - n:i]) and all(hi > w['high'].iloc[i + 1:i + n + 1]):
            return w.index[i], hi
    return None, None


def _prev_swing_low(df15: pd.DataFrame, before_idx, lookback: int = 60, n: int = 3):
    """หา swing low ล่าสุดก่อน before_idx"""
    w = df15[df15.index < before_idx].tail(lookback)
    if len(w) < 2 * n + 1:
        return None, None
    for i in range(len(w) - n - 1, n - 1, -1):
        lo = w['low'].iloc[i]
        if all(lo < w['low'].iloc[i - n:i]) and all(lo < w['low'].iloc[i + 1:i + n + 1]):
            return w.index[i], lo
    return None, None


def bearish_div(df15: pd.DataFrame, m_idx) -> bool:
    """
    Bearish divergence (swing-based):
    Price HH : M High > Previous Swing High
    RSI  LH  : RSI ที่ M < RSI ที่ Swing High
    """
    swing_idx, swing_hi = _prev_swing_high(df15, m_idx)
    if swing_idx is None:
        return False
    m_high = df15.loc[m_idx, 'high']
    return m_high > swing_hi and df15.loc[m_idx, 'rsi'] < df15.loc[swing_idx, 'rsi']


def bullish_div(df15: pd.DataFrame, m_idx) -> bool:
    """
    Bullish divergence (swing-based):
    Price LL : M Low < Previous Swing Low
    RSI  HL  : RSI ที่ M > RSI ที่ Swing Low
    """
    swing_idx, swing_lo = _prev_swing_low(df15, m_idx)
    if swing_idx is None:
        return False
    m_low = df15.loc[m_idx, 'low']
    return m_low < swing_lo and df15.loc[m_idx, 'rsi'] > df15.loc[swing_idx, 'rsi']


# ─── 15m HELPERS ─────────────────────────────────────────────────────────────

def find_mss_short(post_m: pd.DataFrame, m_high: float):
    """MSS Low = low ต่ำสุดใน LEG_CANDLES แท่งแรกหลัง M"""
    w = post_m.head(LEG_CANDLES)
    if w.empty:
        return None, None
    idx = w['low'].idxmin()
    return w['low'].min(), idx


def find_bounce_top(post_mss: pd.DataFrame, mss_low: float, m_high: float):
    """Bounce Top ใน BOUNCE_LOOK แท่งหลัง MSS ต้องอยู่ใน 35-65% retrace"""
    leg = m_high - mss_low
    lo  = mss_low + leg * RETRACE_LO
    hi  = mss_low + leg * RETRACE_HI
    w   = post_mss.head(BOUNCE_LOOK)
    if w.empty:
        return None, None
    peak     = w['high'].max()
    peak_idx = w['high'].idxmax()
    if lo <= peak <= hi:
        return peak, peak_idx
    return None, None


def find_mss_long(post_m: pd.DataFrame, m_low: float):
    """MSS High = high สูงสุดใน LEG_CANDLES แท่งแรกหลัง M"""
    w = post_m.head(LEG_CANDLES)
    if w.empty:
        return None, None
    idx = w['high'].idxmax()
    return w['high'].max(), idx


def find_bounce_bot(post_mss: pd.DataFrame, mss_high: float, m_low: float):
    """Bounce Bottom ใน BOUNCE_LOOK แท่งหลัง MSS ต้องอยู่ใน 35-65% retrace"""
    leg = mss_high - m_low
    lo  = mss_high - leg * RETRACE_HI
    hi  = mss_high - leg * RETRACE_LO
    w   = post_mss.head(BOUNCE_LOOK)
    if w.empty:
        return None, None
    trough     = w['low'].min()
    trough_idx = w['low'].idxmin()
    if lo <= trough <= hi:
        return trough, trough_idx
    return None, None


# ─── 1m MINI-AMD ─────────────────────────────────────────────────────────────

def entry_short_1m(df1m: pd.DataFrame, bounce_top: float):
    """
    1m mini-AMD สำหรับ SHORT:
    Zone = bounce_top ± ZONE_WIDTH
    M    = highest high ใน zone (= SL anchor)
    D    = candle แรก close < zone floor หลัง M → Entry
    """
    zone_hi = bounce_top + 50
    zone_lo = bounce_top - ZONE_WIDTH

    in_zone = df1m[(df1m['low'] <= zone_hi) & (df1m['high'] >= zone_lo)]
    if len(in_zone) < 3:
        return None

    m_wick = in_zone['high'].max()
    m_idx  = in_zone['high'].idxmax()

    # A floor = low ต่ำสุดของ candles ก่อน M (ไม่รวม outlier)
    pre_m   = in_zone[in_zone.index <= m_idx]
    a_floor = pre_m['low'].quantile(0.25)

    after_m = df1m[df1m.index > m_idx]
    for idx, c in after_m.iterrows():
        if c['close'] < a_floor:
            return {
                'entry_time': idx,
                'entry':      c['close'],
                'sl':         round(m_wick + SL_BUFFER, 2),
                'm_wick':     m_wick,
            }
    return None


def entry_long_1m(df1m: pd.DataFrame, bounce_bot: float):
    """
    1m mini-AMD สำหรับ LONG:
    Zone = bounce_bot ± ZONE_WIDTH
    M    = lowest low ใน zone (= SL anchor)
    D    = candle แรก close > zone ceil หลัง M → Entry
    """
    zone_lo = bounce_bot - 50
    zone_hi = bounce_bot + ZONE_WIDTH

    in_zone = df1m[(df1m['high'] >= zone_lo) & (df1m['low'] <= zone_hi)]
    if len(in_zone) < 3:
        return None

    m_wick = in_zone['low'].min()
    m_idx  = in_zone['low'].idxmin()

    pre_m  = in_zone[in_zone.index <= m_idx]
    a_ceil = pre_m['high'].quantile(0.75)

    after_m = df1m[df1m.index > m_idx]
    for idx, c in after_m.iterrows():
        if c['close'] > a_ceil:
            return {
                'entry_time': idx,
                'entry':      c['close'],
                'sl':         round(m_wick - SL_BUFFER, 2),
                'm_wick':     m_wick,
            }
    return None


# ─── SIGNAL DETECTION ────────────────────────────────────────────────────────

def detect_signals(df15: pd.DataFrame, df1m: pd.DataFrame) -> list:
    df = df15.copy()
    df['rsi']  = calc_rsi(df['close'])   # คำนวณ RSI ทั้ง series ก่อน loop
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    signals = []

    for date, day in df.groupby('date'):
        asian = day[day['hour'] < ASIAN_END]
        post  = day[(day['hour'] >= ASIAN_END) & (day['hour'] < MANIP_END)]

        if len(asian) < 8 or post.empty:
            continue

        a_high  = asian['high'].max()
        a_low   = asian['low'].min()
        if a_high - a_low < MIN_RANGE:
            continue

        found = False

        for m_idx, mc in post.iterrows():
            if found:
                break

            # ── SHORT ─────────────────────────────────────────────────────
            if mc['high'] > a_high:
                m_high = mc['high']

                if USE_DIV and not bearish_div(df, m_idx):
                    continue   # ไม่มี bearish divergence → ข้าม

                mss_low, mss_idx = find_mss_short(post[post.index > m_idx], m_high)
                if mss_idx is None:
                    continue

                bounce_top, _ = find_bounce_top(post[post.index > mss_idx], mss_low, m_high)
                if bounce_top is None:
                    continue

                w1m = df1m[
                    (df1m.index >= m_idx) &
                    (df1m.index <= m_idx + pd.Timedelta(hours=8))
                ]
                e = entry_short_1m(w1m, bounce_top)
                if e is None:
                    continue

                leg  = bounce_top - mss_low
                tps  = [round(bounce_top - leg * r, 2) for r in TP_RATIOS]

                signals.append({
                    'date':       date,
                    'direction':  'SHORT',
                    'a_high':     round(a_high, 2),
                    'a_low':      round(a_low, 2),
                    'm_extreme':  round(m_high, 2),
                    'mss_point':  round(mss_low, 2),
                    'bounce_top': round(bounce_top, 2),
                    'fib_leg':    round(leg, 2),
                    'entry_time': e['entry_time'],
                    'entry':      round(e['entry'], 2),
                    'sl':         e['sl'],
                    'tp1':        tps[0],
                    'tp2':        tps[1],
                    'tp3':        tps[2],
                    'risk_pts':   round(e['sl'] - e['entry'], 2),
                })
                found = True

            # ── LONG ──────────────────────────────────────────────────────
            elif mc['low'] < a_low:
                m_low = mc['low']

                if USE_DIV and not bullish_div(df, m_idx):
                    continue   # ไม่มี bullish divergence → ข้าม

                mss_high, mss_idx = find_mss_long(post[post.index > m_idx], m_low)
                if mss_idx is None:
                    continue

                bounce_bot, _ = find_bounce_bot(post[post.index > mss_idx], mss_high, m_low)
                if bounce_bot is None:
                    continue

                w1m = df1m[
                    (df1m.index >= m_idx) &
                    (df1m.index <= m_idx + pd.Timedelta(hours=8))
                ]
                e = entry_long_1m(w1m, bounce_bot)
                if e is None:
                    continue

                leg = mss_high - bounce_bot
                tps = [round(bounce_bot + leg * r, 2) for r in TP_RATIOS]

                signals.append({
                    'date':       date,
                    'direction':  'LONG',
                    'a_high':     round(a_high, 2),
                    'a_low':      round(a_low, 2),
                    'm_extreme':  round(m_low, 2),
                    'mss_point':  round(mss_high, 2),
                    'bounce_top': round(bounce_bot, 2),
                    'fib_leg':    round(leg, 2),
                    'entry_time': e['entry_time'],
                    'entry':      round(e['entry'], 2),
                    'sl':         e['sl'],
                    'tp1':        tps[0],
                    'tp2':        tps[1],
                    'tp3':        tps[2],
                    'risk_pts':   round(e['entry'] - e['sl'], 2),
                })
                found = True

    return signals


# ─── BACKTEST ────────────────────────────────────────────────────────────────

def backtest(df1m: pd.DataFrame, signals: list) -> pd.DataFrame:
    rows = []
    for sig in signals:
        future = df1m[df1m.index > sig['entry_time']]
        tp_status = {'tp1': 'OPEN', 'tp2': 'OPEN', 'tp3': 'OPEN'}
        final = 'OPEN'

        tp1_hit = False  # ถ้า TP1 hit แล้ว SL ถือเป็น breakeven ไม่ใช่ LOSS

        for _, c in future.iterrows():
            short = sig['direction'] == 'SHORT'

            # TP hits (เช็คก่อน SL เพราะ TP1 ใกล้กว่า)
            for key, val in [('tp1', sig['tp1']), ('tp2', sig['tp2']), ('tp3', sig['tp3'])]:
                if tp_status[key] == 'OPEN':
                    hit = c['low'] <= val if short else c['high'] >= val
                    if hit:
                        tp_status[key] = 'WIN'
                        final = 'WIN'
                        if key == 'tp1':
                            tp1_hit = True

            # SL hit
            sl_hit = c['high'] >= sig['sl'] if short else c['low'] <= sig['sl']
            if sl_hit:
                for k, v in tp_status.items():
                    if v == 'OPEN':
                        tp_status[k] = 'LOSS'
                if not tp1_hit:   # ยังไม่ได้ TP1 เลย = LOSS จริง
                    final = 'LOSS'
                # ถ้า TP1 hit ไปแล้ว final ยังเป็น 'WIN' (breakeven หรือมีกำไร)
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
    print(f'  AMD STRATEGY  |  BTCUSDT Perp  |  15m + 1m')
    print(bar)
    print(f'  Period    : {df["date"].min()} → {df["date"].max()}')
    print(f'  Signals   : {len(df)}  (closed {total})')
    print(f'  Win Rate  : {wins/total*100:.1f}%  ({wins}W / {total-wins}L)')
    print(f'  Avg Risk  : ${closed["risk_pts"].mean():,.0f}  per trade')
    print(bar)

    for col, label in [('tp1_status','TP1  350%'), ('tp2_status','TP2  600%'), ('tp3_status','TP3  800%')]:
        hit = len(closed[closed[col] == 'WIN'])
        tot = len(closed[closed[col] != 'OPEN'])
        rr  = float(label.split()[-1].replace('%','')) / 100
        print(f'  {label} : {hit:3d}/{tot:3d} hit  ({hit/tot*100:.0f}%)' if tot else f'  {label} : no data')

    print(bar)
    for d in ['SHORT', 'LONG']:
        sub = closed[closed['direction'] == d]
        if sub.empty:
            continue
        w = len(sub[sub['outcome'] == 'WIN'])
        print(f'  {d:5s}  {len(sub):3d} trades  WR {w/len(sub)*100:.0f}%  avg risk ${sub["risk_pts"].mean():,.0f}')
    print(bar)


# ─── LIVE CHECK (วันนี้) ──────────────────────────────────────────────────────

def live_check():
    """รันดูสถานะ AMD วันนี้ทันที"""
    now      = datetime.now(timezone.utc)
    today_ms = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

    print(f'\nAMD LIVE CHECK  |  {now.strftime("%Y-%m-%d %H:%M")} UTC')
    print('─' * 46)

    df15 = fetch('15m', today_ms)
    df1m = fetch('1m',  today_ms)

    sigs = detect_signals(df15, df1m)

    if not sigs:
        now_h = now.hour
        if now_h < ASIAN_END:
            print(f'  Phase: ACCUMULATION  (Asian session ปิด {ASIAN_END}:00 UTC)')
        else:
            print('  ยังไม่มี setup วันนี้  (รอ Manipulation)')
        return

    sig = sigs[-1]
    price = df1m['close'].iloc[-1]

    print(f'  Direction : {sig["direction"]}')
    print(f'  M extreme : ${sig["m_extreme"]:,.2f}')
    print(f'  MSS point : ${sig["mss_point"]:,.2f}')
    print(f'  Bounce    : ${sig["bounce_top"]:,.2f}  (50% zone)')
    print(f'  Fib leg   : ${sig["fib_leg"]:,.2f}')
    print('─' * 46)
    print(f'  Entry     : ${sig["entry"]:,.2f}')
    print(f'  SL        : ${sig["sl"]:,.2f}  (risk ${sig["risk_pts"]:,.0f})')
    print(f'  TP1 350%  : ${sig["tp1"]:,.2f}  (RR 1:{(abs(sig["tp1"]-sig["entry"])/sig["risk_pts"]):.1f})')
    print(f'  TP2 600%  : ${sig["tp2"]:,.2f}  (RR 1:{(abs(sig["tp2"]-sig["entry"])/sig["risk_pts"]):.1f})')
    print(f'  TP3 800%  : ${sig["tp3"]:,.2f}  (RR 1:{(abs(sig["tp3"]-sig["entry"])/sig["risk_pts"]):.1f})')
    print('─' * 46)
    print(f'  Now price : ${price:,.2f}')


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'live':
        live_check()
    else:
        since_ms = int((datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).timestamp() * 1000)

        print(f'Fetching 15m ({DAYS_BACK}d)...')
        df15 = fetch('15m', since_ms)
        print(f'  {len(df15):,} candles')

        print(f'Fetching 1m  ({DAYS_BACK}d)...')
        df1m = fetch_1m(since_ms)
        print()

        sigs = detect_signals(df15, df1m)
        print(f'Signals found : {len(sigs)}')

        if sigs:
            results = backtest(df1m, sigs)
            print_summary(results)
            results.to_csv('amd_full_results.csv', index=False)
            print('\nSaved → amd_full_results.csv')
