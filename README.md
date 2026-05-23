# BTC Trading — AMD + V+M Strategies

ระบบเทรด BTCUSDT Perpetual บน **Pionex Futures** ด้วย 2 กลยุทธ์คู่กัน

## Strategies

| Strategy | เหมาะกับ | Entry direction | Script |
|---|---|---|---|
| **AMD** (Accumulation/Manipulation/Distribution) | ตลาด range / มี sweep ชัด | LONG / SHORT | `amd_full.py` |
| **V+M** (V reversal + M กลับหัว) | Uptrend | LONG only | `vm_backtest.py` |

Strategy เต็มอยู่ใน [`Trade.md`](Trade.md)

## Account Setup

- **Exchange**: Crypto futures (any — Binance/Bybit/Pionex/etc.)
- **Position sizing**: ตามดุลพินิจ (margin, leverage, budget) — เก็บเป็น private notes
- **Tested on**: high leverage (50x+) crypto futures

## Universal Rules

- **Minimum fib_leg: $150** (filter thin setups)
- **TP scale-out 3 ระดับเสมอ**: 350% / 600% / 800% ของ fib_leg
- **Timeout**: ไม่มี hard timeout — setup ค้างได้ถ้า structure ยังไม่เสีย (retrace ≤ 65%, ไม่มี M ใหม่)

## Install

```bash
pip3 install -r requirements.txt
```

## Usage

### เช็ค setup ปัจจุบัน (รัน 2 คำสั่งคู่กัน)

```bash
python3 amd_full.py live      # text strategy verdict
python3 chart_setup.py        # chart visualization (auto-open Preview)
```

### Backtest 90 วัน

```bash
python3 amd_full.py           # AMD backtest
python3 vm_backtest.py        # V+M backtest
```

## Files

| File | หน้าที่ |
|---|---|
| `Trade.md` | Strategy doc เต็ม + checklist |
| `amd_full.py` | AMD backtest + live (มี RSI div filter) |
| `amd_check.py` | Simple 15m-only check (เก่า, RR 1:2 ไม่ตรงสูตร) |
| `amd_backtest.py` | Basic AMD version (ไม่มี 1m) |
| `vm_backtest.py` | V+M backtest + live |
| `chart_setup.py` | Dark-theme chart generator (AMD SHORT) |
| `CLAUDE_PROMPT.md` | Prompt สำหรับ bootstrap project บนเครื่องใหม่ |

## Report Layout (Checklist-first)

```
AMD SHORT  |  BTCUSDT 15m  |  {TIME UTC}  |  ${PRICE}
────────────────────────────────────────
 □ Asian range > $200       ✅/⏳/❌
 □ M sweep                   ✅/⏳/❌
 □ MSS first leg ชัด         ✅/⏳/❌
 □ Bounce 35-65%             ✅/⏳/❌
 □ 1m mini-AMD A→M→D         ✅/⏳/❌
 □ RSI divergence (15m)      ✅/⏳/❌
 □ fib_leg ≥ $150            ✅/⏳/❌

 VERDICT  :  ✅ เข้า | ❌ ยังไม่เข้า | ⏳ รอ
 NEXT     :  เงื่อนไขถัดไป
────────────────────────────────────────
Entry $E  SL $SL  risk $R
   TP1 350% : $T1   RR 1:rr1
   TP2 600% : $T2   RR 1:rr2
   TP3 800% : $T3   RR 1:rr3
────────────────────────────────────────
⚠️ warnings
```

## Pending Work

- [ ] เก็บ trade log จริงเพื่อ validate กับ backtest
- [ ] ต่อ API key สำหรับ auto mode (เมื่อพร้อม)
