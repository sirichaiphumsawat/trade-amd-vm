#!/usr/bin/env python3
"""
AMD Pattern Backtest — BTCUSDT Perpetual (Binance) 15m
Accumulation (Asian 00-08 UTC) → Manipulation → Distribution
"""

import ccxt
import pandas as pd
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# ─── CONFIG ────────────────────────────────────────────────────────────────
SYMBOL       = 'BTC/USDT:USDT'   # Binance USDM Perpetual
TIMEFRAME    = '15m'
DAYS_BACK    = 180

ASIAN_START  = 0    # UTC hour (inclusive)
ASIAN_END    = 8    # UTC hour (exclusive)
MANIP_START  = 8    # London open
MANIP_END    = 17   # NY close

MIN_RANGE    = 100  # ข้าม Asian range ที่แคบกว่า $100
REWARD_RISK  = 2.0  # TP = 2R
# ───────────────────────────────────────────────────────────────────────────


def fetch_data() -> pd.DataFrame:
    exchange = ccxt.binanceusdm({'enableRateLimit': True})
    since_ms = int((datetime.utcnow() - timedelta(days=DAYS_BACK)).timestamp() * 1000)

    print(f"Fetching {SYMBOL} {TIMEFRAME} ({DAYS_BACK} days)...")
    all_ohlcv = []
    while True:
        batch = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, since=since_ms, limit=1000)
        if not batch:
            break
        all_ohlcv.extend(batch)
        if len(batch) < 1000:
            break
        since_ms = batch[-1][0] + 1

    df = pd.DataFrame(all_ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df = df.set_index('ts').sort_index()
    df = df[~df.index.duplicated()]
    print(f"  {len(df)} candles  |  {df.index[0].date()} → {df.index[-1].date()}\n")
    return df


def detect_signals(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    df['date'] = df.index.date
    df['hour'] = df.index.hour

    signals = []

    for date, day in df.groupby('date'):
        asian     = day[(day['hour'] >= ASIAN_START) & (day['hour'] < ASIAN_END)]
        post      = day[(day['hour'] >= MANIP_START) & (day['hour'] < MANIP_END)]

        if len(asian) < 8 or len(post) == 0:
            continue

        a_high = asian['high'].max()
        a_low  = asian['low'].min()
        a_range = a_high - a_low

        if a_range < MIN_RANGE:
            continue

        found = False

        for idx, candle in post.iterrows():
            if found:
                break

            # ── Manipulation UP → SHORT setup ──────────────────────────────
            if candle['high'] > a_high:
                manip_extreme = candle['high']
                after = post[post.index > idx]

                for eidx, ec in after.iterrows():
                    if ec['close'] < a_high:          # ราคากลับเข้า range
                        entry = ec['close']
                        sl    = manip_extreme
                        risk  = sl - entry
                        if risk <= 0:
                            continue
                        tp = entry - risk * REWARD_RISK
                        signals.append({
                            'date':          date,
                            'direction':     'SHORT',
                            'a_high':        round(a_high, 2),
                            'a_low':         round(a_low, 2),
                            'a_range':       round(a_range, 2),
                            'manip_time':    idx,
                            'manip_extreme': round(manip_extreme, 2),
                            'entry_time':    eidx,
                            'entry':         round(entry, 2),
                            'sl':            round(sl, 2),
                            'tp':            round(tp, 2),
                            'risk_pts':      round(risk, 2),
                        })
                        found = True
                        break

            # ── Manipulation DOWN → LONG setup ─────────────────────────────
            elif candle['low'] < a_low:
                manip_extreme = candle['low']
                after = post[post.index > idx]

                for eidx, ec in after.iterrows():
                    if ec['close'] > a_low:           # ราคากลับเข้า range
                        entry = ec['close']
                        sl    = manip_extreme
                        risk  = entry - sl
                        if risk <= 0:
                            continue
                        tp = entry + risk * REWARD_RISK
                        signals.append({
                            'date':          date,
                            'direction':     'LONG',
                            'a_high':        round(a_high, 2),
                            'a_low':         round(a_low, 2),
                            'a_range':       round(a_range, 2),
                            'manip_time':    idx,
                            'manip_extreme': round(manip_extreme, 2),
                            'entry_time':    eidx,
                            'entry':         round(entry, 2),
                            'sl':            round(sl, 2),
                            'tp':            round(tp, 2),
                            'risk_pts':      round(risk, 2),
                        })
                        found = True
                        break

    return signals


def backtest(df: pd.DataFrame, signals: list[dict]) -> pd.DataFrame:
    rows = []

    for sig in signals:
        future = df[df.index > sig['entry_time']]
        outcome    = 'TIMEOUT'
        pnl_r      = 0.0
        exit_time  = None
        exit_price = None

        for idx, c in future.iterrows():
            if sig['direction'] == 'SHORT':
                if c['high'] >= sig['sl']:
                    outcome, pnl_r, exit_price, exit_time = 'LOSS', -1.0, sig['sl'], idx
                    break
                if c['low'] <= sig['tp']:
                    outcome, pnl_r, exit_price, exit_time = 'WIN', REWARD_RISK, sig['tp'], idx
                    break
            else:
                if c['low'] <= sig['sl']:
                    outcome, pnl_r, exit_price, exit_time = 'LOSS', -1.0, sig['sl'], idx
                    break
                if c['high'] >= sig['tp']:
                    outcome, pnl_r, exit_price, exit_time = 'WIN', REWARD_RISK, sig['tp'], idx
                    break

        rows.append({
            **sig,
            'outcome':    outcome,
            'pnl_r':      pnl_r,
            'exit_time':  exit_time,
            'exit_price': exit_price,
        })

    return pd.DataFrame(rows)


def print_summary(results: pd.DataFrame):
    closed = results[results['outcome'] != 'TIMEOUT'].copy()
    if closed.empty:
        print("No closed trades found.")
        return

    wins   = closed[closed['outcome'] == 'WIN']
    losses = closed[closed['outcome'] == 'LOSS']
    total  = len(closed)
    wr     = len(wins) / total * 100

    closed_sorted = closed.sort_values('entry_time')
    closed_sorted['cum_r'] = closed_sorted['pnl_r'].cumsum()
    max_dd = (closed_sorted['cum_r'].cummax() - closed_sorted['cum_r']).max()

    bar = "=" * 52
    print(f"\n{bar}")
    print(f"  AMD BACKTEST  |  BTCUSDT 15m  |  RR 1:{REWARD_RISK}")
    print(bar)
    print(f"  Period       : {results['date'].min()} → {results['date'].max()}")
    print(f"  Signals      : {len(results)}  (closed: {total})")
    print(f"  Win Rate     : {wr:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Total R      : {closed['pnl_r'].sum():+.2f}R")
    print(f"  Avg R/trade  : {closed['pnl_r'].mean():+.2f}R")
    print(f"  Max Drawdown : {max_dd:.2f}R")
    print(bar)

    for d in ['LONG', 'SHORT']:
        sub = closed[closed['direction'] == d]
        if sub.empty:
            continue
        w = len(sub[sub['outcome'] == 'WIN'])
        print(f"  {d:5s}  {len(sub):3d} trades  |  WR {w/len(sub)*100:.0f}%  |  {sub['pnl_r'].sum():+.1f}R")

    print(bar)
    return closed_sorted


if __name__ == '__main__':
    df      = fetch_data()
    signals = detect_signals(df)
    print(f"Signals detected: {len(signals)}")

    if not signals:
        print("No AMD signals found. Try increasing DAYS_BACK.")
    else:
        results = backtest(df, signals)
        print_summary(results)

        out = 'amd_backtest_results.csv'
        results.to_csv(out, index=False)
        print(f"\nSaved → {out}")
