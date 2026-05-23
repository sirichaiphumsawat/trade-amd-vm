#!/usr/bin/env python3
"""
chart_setup.py — สร้างภาพ AMD SHORT setup chart จาก Binance 15m data

Output: /tmp/btc_amd_chart.png  +  เปิดอัตโนมัติบน macOS

Usage:
    python3 chart_setup.py            # ใช้ data ปัจจุบัน
    python3 chart_setup.py --no-open  # ไม่เปิด Preview อัตโนมัติ
"""

import urllib.request
import json
import os
import sys
import subprocess
from datetime import datetime, timezone
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import mplfinance as mpf

# ─── CONFIG ──────────────────────────────────────────────────────────────────
SYMBOL          = "BTCUSDT"
TF              = "15m"
LOOKBACK        = 80          # candles to display
ASIAN_END       = 8           # UTC hour
LEG_CANDLES     = 16          # MSS search window after M
RETRACE_LO      = 0.35        # bounce zone low
RETRACE_HI      = 0.65        # bounce zone high
FIB_LEG_MIN     = 150         # USD
OUTPUT_DIR      = os.path.expanduser("~/Documents/btc_charts")
LATEST_LINK     = os.path.join(OUTPUT_DIR, "latest.png")

# Colors — dark theme (TradingView Pro inspired)
BG              = "#0f1116"   # near-black background
GRID            = "#1d2028"   # subtle grid
TEXT            = "#d6d9e0"   # light text
TEXT_DIM        = "#8a8f9a"   # dim text
WICK_UP         = "#d6d9e0"
WICK_DN         = "#d6d9e0"
BODY_UP         = "#e8eaef"   # near-white up
BODY_DN         = "#0f1116"   # same as bg (hollow look)
RB_COLOR        = "#c75450"   # rejection block (red)
ENTRY_COLOR     = "#d4a45c"   # entry zone (gold)
TP_COLOR        = "#4caf7d"   # green tp
SL_COLOR        = "#e87060"   # red sl
ASIAN_COLOR     = "#5a6e9a"   # asian range (blue)

# ─── DATA ────────────────────────────────────────────────────────────────────
def fetch_klines():
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={SYMBOL}&interval={TF}&limit=200"
    data = json.loads(urllib.request.urlopen(url, timeout=15).read())
    df = pd.DataFrame(data, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","qav","trades","tbbav","tbqav","ignore"
    ])
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.set_index("ts", inplace=True)
    return df[["open","high","low","close","volume"]]


def fetch_price():
    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={SYMBOL}"
    return float(json.loads(urllib.request.urlopen(url, timeout=10).read())["price"])


# ─── DETECT AMD STRUCTURE ─────────────────────────────────────────────────────
def detect_amd_short(df):
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_df  = df[df.index.strftime("%Y-%m-%d") == today_utc]
    if today_df.empty:
        return None

    asian = today_df[today_df.index.hour < ASIAN_END]
    london = today_df[today_df.index.hour >= ASIAN_END]
    if asian.empty or london.empty:
        return None

    asian_high = asian["high"].max()
    asian_low  = asian["low"].min()
    asian_open_ts = asian.index[0]
    asian_close_ts = asian.index[-1]

    # M extreme = first / highest high after 08:00 above asian_high
    swept = london[london["high"] > asian_high]
    if swept.empty:
        return {
            "asian_high": asian_high, "asian_low": asian_low,
            "asian_open": asian_open_ts, "asian_close": asian_close_ts,
            "m": None,
        }
    m_ts = swept["high"].idxmax()
    m_high = swept.loc[m_ts, "high"]

    # MSS Low = lowest low in next LEG_CANDLES after M
    post_m = london[london.index > m_ts].head(LEG_CANDLES)
    if post_m.empty:
        return {
            "asian_high": asian_high, "asian_low": asian_low,
            "asian_open": asian_open_ts, "asian_close": asian_close_ts,
            "m_ts": m_ts, "m_high": m_high,
            "mss": None,
        }
    mss_ts = post_m["low"].idxmin()
    mss_low = post_m.loc[mss_ts, "low"]

    first_leg = m_high - mss_low

    # Bounce Top = highest high AFTER MSS within 35-65% retrace
    post_mss = london[london.index > mss_ts]
    lo = mss_low + first_leg * RETRACE_LO
    hi = mss_low + first_leg * RETRACE_HI
    in_zone = post_mss[(post_mss["high"] >= lo) & (post_mss["high"] <= hi)]
    bounce_ts = None
    bounce_top = None
    if not in_zone.empty:
        bounce_ts = in_zone["high"].idxmax()
        bounce_top = in_zone.loc[bounce_ts, "high"]
    else:
        # Take highest high after MSS regardless of zone (for chart context)
        if not post_mss.empty:
            bounce_ts = post_mss["high"].idxmax()
            bounce_top = post_mss.loc[bounce_ts, "high"]

    return {
        "asian_high": asian_high, "asian_low": asian_low,
        "asian_open": asian_open_ts, "asian_close": asian_close_ts,
        "m_ts": m_ts, "m_high": m_high,
        "mss_ts": mss_ts, "mss_low": mss_low,
        "first_leg": first_leg,
        "bounce_ts": bounce_ts, "bounce_top": bounce_top,
        "rb_lo": lo, "rb_hi": hi,
    }


# ─── PLOT ────────────────────────────────────────────────────────────────────
def make_chart(df, setup, price, output_path=None):
    plot_df = df.tail(LOOKBACK).copy()

    mc = mpf.make_marketcolors(
        up=BODY_UP, down=BODY_DN,
        edge={"up": WICK_UP, "down": WICK_DN},
        wick={"up": WICK_UP, "down": WICK_DN},
        ohlc="inherit",
    )
    s = mpf.make_mpf_style(
        base_mpf_style="charles",
        marketcolors=mc,
        facecolor=BG,
        figcolor=BG,
        edgecolor=GRID,
        gridcolor=GRID,
        gridstyle=":",
        rc={"axes.labelcolor": TEXT, "axes.edgecolor": GRID,
            "xtick.color": TEXT_DIM, "ytick.color": TEXT_DIM,
            "axes.facecolor": BG},
    )

    fig, axes = mpf.plot(
        plot_df,
        type="candle",
        style=s,
        returnfig=True,
        figsize=(14, 9),
        ylabel="",
        xrotation=0,
        datetime_format="%H:%M",
        tight_layout=False,
    )
    ax = axes[0]

    # Right-side padding so labels don't get clipped
    x_lo, x_hi = ax.get_xlim()
    pad = (x_hi - x_lo) * 0.12
    ax.set_xlim(x_lo, x_hi + pad)
    label_x = x_hi + pad * 0.55

    # Helper: convert timestamp to plot x-index in plot_df
    def ts_to_x(ts):
        try:
            return plot_df.index.get_loc(ts)
        except KeyError:
            # closest before
            sub = plot_df.index[plot_df.index <= ts]
            return plot_df.index.get_loc(sub[-1]) if len(sub) else 0

    # Asian Range rectangle
    if setup and setup.get("asian_high"):
        x_start = ts_to_x(setup["asian_open"])
        x_end   = ts_to_x(setup["asian_close"])
        ax.add_patch(patches.Rectangle(
            (x_start, setup["asian_low"]),
            x_end - x_start + 1,
            setup["asian_high"] - setup["asian_low"],
            facecolor=ASIAN_COLOR, alpha=0.18, edgecolor="none", zorder=0,
        ))
        ax.text(x_start + 0.3, setup["asian_high"] - 8,
                "Asian", fontsize=9, color=TEXT_DIM, alpha=0.9,
                ha="left", va="top", style="italic")

    # M, MSS markers
    if setup and setup.get("m_high"):
        x = ts_to_x(setup["m_ts"])
        ax.scatter([x], [setup["m_high"]], marker="v", s=70,
                   color=SL_COLOR, zorder=5)
        ax.annotate(f"M  ${setup['m_high']:,.0f}",
                    xy=(x, setup["m_high"]),
                    xytext=(x - 6, setup["m_high"] + 40),
                    fontsize=9, color=SL_COLOR, fontweight="bold")
    if setup and setup.get("mss_low"):
        x = ts_to_x(setup["mss_ts"])
        ax.scatter([x], [setup["mss_low"]], marker="^", s=70,
                   color=TP_COLOR, zorder=5)
        ax.annotate(f"MSS  ${setup['mss_low']:,.0f}",
                    xy=(x, setup["mss_low"]),
                    xytext=(x - 6, setup["mss_low"] - 80),
                    fontsize=9, color=TP_COLOR, fontweight="bold")

    # RB zone (50% Fibo bounce target) — center on 50%, width ±7.5%
    if setup and setup.get("bounce_top") is not None:
        mss = setup["mss_low"]
        leg = setup["first_leg"]
        rb_lo = mss + leg * 0.475
        rb_hi = mss + leg * 0.625
        x_start = ts_to_x(setup["mss_ts"]) + 2
        rb_width = (x_hi - x_start) + pad * 0.55
        ax.add_patch(patches.Rectangle(
            (x_start, rb_lo), rb_width, rb_hi - rb_lo,
            facecolor=RB_COLOR, alpha=0.45, edgecolor="none", zorder=2,
        ))
        ax.text(x_start + rb_width * 0.35, (rb_lo + rb_hi) / 2,
                "RB", fontsize=11, color="#ffe0dc",
                ha="center", va="center", fontweight="bold", style="italic")
        ax.text(x_start + rb_width * 0.95, (rb_lo + rb_hi) / 2,
                f"${rb_lo:,.0f} – ${rb_hi:,.0f}",
                fontsize=9, color="#ffe0dc",
                ha="right", va="center", fontweight="bold")

        # ENTRY zone (just below RB, 30-40% area)
        ent_lo = mss + leg * 0.30
        ent_hi = mss + leg * 0.40
        ax.add_patch(patches.Rectangle(
            (x_start, ent_lo), rb_width, ent_hi - ent_lo,
            facecolor=ENTRY_COLOR, alpha=0.55, edgecolor="none", zorder=2,
        ))
        ax.text(x_start + rb_width * 0.35, (ent_lo + ent_hi) / 2,
                "ENTRY", fontsize=10, color="#fff0d6",
                ha="center", va="center", fontweight="bold", style="italic")
        ax.text(x_start + rb_width * 0.95, (ent_lo + ent_hi) / 2,
                f"${ent_lo:,.0f} – ${ent_hi:,.0f}",
                fontsize=9, color="#fff0d6",
                ha="right", va="center", fontweight="bold")

        # Projection: current price → up to RB → back to ENTRY → just below MSS
        last_x = len(plot_df) - 1
        last_close = plot_df["close"].iloc[-1]
        rb_mid = (rb_lo + rb_hi) / 2
        ent_mid = (ent_lo + ent_hi) / 2

        # Short projection (visible target = MSS - small dip, NOT full TP1)
        target_y = mss - leg * 0.3
        target_x = last_x + 7
        peak_x = last_x + 2
        dip_x = last_x + 4
        proj_x = [last_x, peak_x, dip_x, target_x]
        proj_y = [last_close, rb_mid, ent_mid, target_y]
        ax.plot(proj_x, proj_y, linestyle=":", color=TEXT,
                linewidth=1.5, alpha=0.7, zorder=3)

    # Current price marker
    ax.axhline(price, color=TEXT, linestyle="-",
               linewidth=0.6, alpha=0.4, zorder=1)
    ax.text(label_x, price, f"${price:,.1f}",
            fontsize=10, color="#0f1116", va="center", ha="left", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor=TEXT,
                      edgecolor="none"))

    # Zoom y-axis to focus on action area (don't let TP3 stretch it)
    visible_hi = plot_df["high"].max()
    visible_lo = plot_df["low"].min()
    if setup and setup.get("m_high"):
        visible_hi = max(visible_hi, setup["m_high"])
    if setup and setup.get("mss_low"):
        visible_lo = min(visible_lo, setup["mss_low"])
    pad_y = (visible_hi - visible_lo) * 0.18
    ax.set_ylim(visible_lo - pad_y, visible_hi + pad_y)

    # TP labels at the very bottom edge (outside main action zone)
    if setup and setup.get("bounce_top") is not None:
        mss = setup["mss_low"]
        leg = setup["first_leg"]
        rb_mid = mss + leg * 0.55
        fib_leg_est = rb_mid - mss
        y_lo, y_hi = ax.get_ylim()
        tp_summary = []
        for mult, label in [(3.5, "TP1"), (6.0, "TP2"), (8.0, "TP3")]:
            tp = rb_mid - fib_leg_est * mult
            tp_summary.append(f"{label} ${tp:,.0f}")
        ax.text(label_x, y_lo + (y_hi - y_lo) * 0.04,
                "\n".join(tp_summary), fontsize=9, color=TP_COLOR,
                va="bottom", ha="left", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.4", facecolor="#162820",
                          edgecolor=TP_COLOR, linewidth=0.8))

    # Title
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fib_leg_val = setup.get("first_leg", 0) if setup else 0
    fib_status = "✓" if fib_leg_val >= FIB_LEG_MIN else "small"
    title = f"AMD SHORT  |  {SYMBOL} {TF}  |  {now_utc}  |  fib_leg ${fib_leg_val:,.0f} {fib_status}"
    ax.set_title(title, fontsize=11, color=TEXT, loc="left", pad=10)

    if output_path:
        # Custom path (e.g. /tmp/chart.png for Telegram) — no symlink, no dir mgmt
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        plt.savefig(output_path, dpi=140, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return output_path

    # Default: write to ~/Documents/btc_charts/ + maintain "latest" symlink
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    fname = f"btc_amd_{stamp}.png"
    out_path = os.path.join(OUTPUT_DIR, fname)
    plt.savefig(out_path, dpi=140, facecolor=BG, bbox_inches="tight")
    plt.close(fig)

    if os.path.lexists(LATEST_LINK):
        os.remove(LATEST_LINK)
    os.symlink(fname, LATEST_LINK)

    return out_path


# ─── LIBRARY API (used by monitor_ci.py) ─────────────────────────────────────
def build_amd_short_chart(output_path=None):
    """
    Generate AMD SHORT chart and return path.

    Args:
        output_path: full path to write PNG (e.g. /tmp/chart.png).
                     If None → use default OUTPUT_DIR/btc_amd_<stamp>.png

    Returns:
        path to chart on success, None if structure not ready.
    """
    df = fetch_klines()
    price = fetch_price()
    setup = detect_amd_short(df)

    if not setup or not setup.get("m_high") or not setup.get("mss_low"):
        return None

    return make_chart(df, setup, price, output_path=output_path)


# ─── VM LONG CHART ───────────────────────────────────────────────────────────
def build_vm_long_chart(signal, output_path=None):
    """
    Generate V+M LONG chart from a pre-detected signal.

    Args:
        signal: dict with at least neckline, v_low, w_low, entry, sl, tp1/2/3.
                Must come from monitor_ci.check_vm() output.
        output_path: full path to write PNG, or None for default dir.

    Returns:
        path to chart on success, None if signal incomplete.
    """
    required = ("neckline", "v_low", "w_low", "entry", "sl", "tp1", "tp2", "tp3")
    if not all(signal.get(k) is not None for k in required):
        return None

    df = fetch_klines()
    price = fetch_price()
    return _render_vm_chart(df, signal, price, output_path)


def _render_vm_chart(df, sig, price, output_path):
    """Render V+M structure: V bottom + neckline + W Higher Low + entry/SL/TPs."""
    plot_df = df.tail(LOOKBACK).copy()

    mc = mpf.make_marketcolors(
        up=BODY_UP, down=BODY_DN,
        edge={"up": WICK_UP, "down": WICK_DN},
        wick={"up": WICK_UP, "down": WICK_DN},
        ohlc="inherit",
    )
    s = mpf.make_mpf_style(
        base_mpf_style="charles", marketcolors=mc,
        facecolor=BG, figcolor=BG, edgecolor=GRID,
        gridcolor=GRID, gridstyle=":",
        rc={"axes.labelcolor": TEXT, "axes.edgecolor": GRID,
            "xtick.color": TEXT_DIM, "ytick.color": TEXT_DIM,
            "axes.facecolor": BG},
    )

    fig, axes = mpf.plot(
        plot_df, type="candle", style=s, returnfig=True,
        figsize=(14, 9), ylabel="", xrotation=0,
        datetime_format="%H:%M", tight_layout=False,
    )
    ax = axes[0]

    # Right-side padding for labels
    x_lo, x_hi = ax.get_xlim()
    pad = (x_hi - x_lo) * 0.12
    ax.set_xlim(x_lo, x_hi + pad)
    label_x = x_hi + pad * 0.55

    neckline = sig["neckline"]
    v_low    = sig["v_low"]
    w_low    = sig["w_low"]
    entry    = sig["entry"]
    sl       = sig["sl"]
    tp1, tp2, tp3 = sig["tp1"], sig["tp2"], sig["tp3"]

    # Find V bottom and W low positions in plot_df (closest match)
    def find_x(price_target, window):
        """Find x-index of candle whose low is closest to price_target."""
        diffs = (plot_df["low"] - price_target).abs()
        idx = diffs.idxmin()
        return plot_df.index.get_loc(idx)

    v_x = find_x(v_low, plot_df)
    w_x = find_x(w_low, plot_df)

    # Neckline horizontal line (key level)
    ax.axhline(neckline, color=ENTRY_COLOR, linestyle="--",
               linewidth=1.4, alpha=0.85, zorder=2)
    ax.text(label_x, neckline,
            f"Neck ${neckline:,.0f}",
            fontsize=9, color="#0f1116", va="center", ha="left", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor=ENTRY_COLOR, edgecolor="none"))

    # V bottom marker (deep low — red v)
    ax.scatter([v_x], [v_low], marker="v", s=80,
               color=SL_COLOR, zorder=5)
    ax.annotate(f"V  ${v_low:,.0f}",
                xy=(v_x, v_low),
                xytext=(v_x - 6, v_low - 60),
                fontsize=9, color=SL_COLOR, fontweight="bold")

    # W Higher Low marker (green ^ — bullish confirmation)
    ax.scatter([w_x], [w_low], marker="^", s=80,
               color=TP_COLOR, zorder=5)
    ax.annotate(f"W (HL)  ${w_low:,.0f}",
                xy=(w_x, w_low),
                xytext=(w_x - 6, w_low - 60),
                fontsize=9, color=TP_COLOR, fontweight="bold")

    # Connect V → W with dashed line (shows Higher Low structure)
    ax.plot([v_x, w_x], [v_low, w_low],
            linestyle="--", color=TEXT_DIM, linewidth=1, alpha=0.5, zorder=1)

    # Entry zone (band ±30 around entry, just above neckline)
    last_x = len(plot_df) - 1
    ent_band = 30
    ax.add_patch(patches.Rectangle(
        (w_x, entry - ent_band),
        (last_x + 3) - w_x,
        ent_band * 2,
        facecolor=ENTRY_COLOR, alpha=0.35, edgecolor="none", zorder=2,
    ))
    ax.text(label_x, entry,
            f"Entry ${entry:,.0f}",
            fontsize=9, color="#0f1116", va="center", ha="left", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor=ENTRY_COLOR, edgecolor="none"))

    # SL line (red)
    ax.axhline(sl, color=SL_COLOR, linestyle=":", linewidth=1, alpha=0.7, zorder=1)
    ax.text(label_x, sl,
            f"SL ${sl:,.0f}",
            fontsize=8, color=SL_COLOR, va="center", ha="left", fontweight="bold")

    # Current price marker
    ax.axhline(price, color=TEXT, linestyle="-",
               linewidth=0.6, alpha=0.4, zorder=1)
    ax.text(label_x, price, f"${price:,.1f}",
            fontsize=10, color="#0f1116", va="center", ha="left", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor=TEXT, edgecolor="none"))

    # Projection: current price → up through neckline → toward TP1
    last_close = plot_df["close"].iloc[-1]
    target_y = entry + (tp1 - entry) * 0.4  # partial path toward TP1
    proj_x = [last_x, last_x + 3, last_x + 6]
    proj_y = [last_close, neckline + 20, target_y]
    ax.plot(proj_x, proj_y, linestyle=":", color=TP_COLOR,
            linewidth=1.5, alpha=0.7, zorder=3)

    # Zoom y to action area (don't let TP3 stretch it)
    visible_hi = max(plot_df["high"].max(), neckline, entry)
    visible_lo = min(plot_df["low"].min(), v_low, sl)
    pad_y = (visible_hi - visible_lo) * 0.18
    ax.set_ylim(visible_lo - pad_y, visible_hi + pad_y)

    # TP labels in box (lower right, outside main action zone)
    y_lo, y_hi = ax.get_ylim()
    tp_summary = [
        f"TP1 ${tp1:,.0f}",
        f"TP2 ${tp2:,.0f}",
        f"TP3 ${tp3:,.0f}",
    ]
    ax.text(label_x, y_hi - (y_hi - y_lo) * 0.06,
            "\n".join(tp_summary), fontsize=9, color=TP_COLOR,
            va="top", ha="left", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#162820",
                      edgecolor=TP_COLOR, linewidth=0.8))

    # Title
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fib_leg = sig.get("fib_leg", neckline - w_low)
    title = (f"V+M LONG  |  {SYMBOL} {TF}  |  {now_utc}  |  "
             f"fib_leg ${fib_leg:,.0f} ✓")
    ax.set_title(title, fontsize=11, color=TEXT, loc="left", pad=10)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        plt.savefig(output_path, dpi=140, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return output_path

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    fname = f"btc_vm_{stamp}.png"
    out_path = os.path.join(OUTPUT_DIR, fname)
    plt.savefig(out_path, dpi=140, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    force = "--force" in sys.argv
    print(f"Fetching {SYMBOL} {TF}...")
    df = fetch_klines()
    price = fetch_price()
    print(f"  {len(df)} candles  |  current ${price:,.2f}")

    setup = detect_amd_short(df)

    # Skip render if structure ยังไม่ก่อตัวพอที่จะวาด zone ได้ (--force เพื่อ override)
    if not force:
        if not setup or not setup.get("m_high") or not setup.get("mss_low"):
            reason = "Asian session ยังไม่ปิด" if not (setup and setup.get("m_high")) else "M sweep แล้ว แต่ยังไม่มี MSS Low"
            print(f"\n⏭  Skip chart — {reason}")
            print(f"   ไม่มี structure ให้ mark — ใช้ --force ถ้าอยากดูแค่ candles")
            return

    if setup:
        print(f"Asian: ${setup['asian_low']:,.0f} – ${setup['asian_high']:,.0f}")
        if setup.get("m_high"):
            print(f"M    : ${setup['m_high']:,.0f}  ({setup['m_ts'].strftime('%H:%M UTC')})")
        if setup.get("mss_low"):
            print(f"MSS  : ${setup['mss_low']:,.0f}  ({setup['mss_ts'].strftime('%H:%M UTC')})")
            print(f"Leg  : ${setup['first_leg']:,.0f}")
        if setup.get("bounce_top"):
            ret = (setup["bounce_top"] - setup["mss_low"]) / setup["first_leg"] * 100
            print(f"Bnce : ${setup['bounce_top']:,.0f}  ({ret:.0f}% retrace)")

    out = make_chart(df, setup, price)
    print(f"\nSaved: {out}")

    if "--no-open" not in sys.argv:
        subprocess.run(["open", out], check=False)


if __name__ == "__main__":
    main()
