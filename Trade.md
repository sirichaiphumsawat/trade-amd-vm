# Trading Strategies — BTCUSDT Perpetual (Binance)

## Overview
- **Asset**: BTCUSDT Perpetual (Binance USDM Futures)
- **Main TF**: 15m
- **Entry TF**: 1m
- **Style**: Manual → Auto (เมื่อมั่นใจพอ)
- **Filter**: RSI Divergence (15m)

---

## Session Times (UTC)

| Session | เวลา UTC | บทบาท |
|---|---|---|
| Asian | 00:00 – 08:00 | Accumulation (A) |
| London | 08:00 – 13:00 | Manipulation (M) |
| New York | 13:00 – 17:00 | Distribution (D) |

---

## Full Setup Logic

### Phase A — Accumulation (Asian Session)
- วาด **Asian High** และ **Asian Low** จาก candle 00:00–08:00 UTC
- Asian Range ต้องกว้างกว่า **$200** (กรอง range แคบ)

---

### Phase M — Manipulation (หลัง 08:00 UTC)
- **SHORT**: candle 15m ที่ high **เกิน Asian High** = Manipulation UP
- **LONG**: candle 15m ที่ low **ต่ำกว่า Asian Low** = Manipulation DOWN
- บันทึก **M Extreme** (high/low สูงสุดของแท่ง M)

#### RSI Divergence Filter (15m) ← ต้องผ่านก่อนเข้า setup
- **SHORT**: ราคาทำ Higher High ที่ M แต่ RSI ทำ Lower High = Bearish Divergence ✅
- **LONG**: ราคาทำ Lower Low ที่ M แต่ RSI ทำ Higher Low = Bullish Divergence ✅
- ไม่มี divergence = ข้าม setup วันนี้

---

### MSS — First Leg หลัง M
- **SHORT**: หา low ต่ำสุดใน 16 แท่ง 15m แรกหลัง M = **MSS Low**
- **LONG**: หา high สูงสุดใน 16 แท่ง 15m แรกหลัง M = **MSS High**

```
SHORT:  M High → MSS Low    (first leg ลง)
LONG:   M Low  → MSS High   (first leg ขึ้น)
```

---

### 50% Fibonacci Retracement
วัดจาก **MSS Point → Bounce** โดยใช้ Fibonacci Retracement

```
SHORT:
  จุดล่าง (0%)   = MSS Low
  จุดบน  (100%)  = Bounce Top  ← ราคา retrace กลับขึ้นมา

LONG:
  จุดบน  (0%)    = MSS High
  จุดล่าง(100%)  = Bounce Bottom
```

- Bounce ต้องอยู่ใน **35–65%** ของ first leg (ยอมรับ tolerance)
- ถ้า retrace เกิน 65% = setup invalidate

---

### Entry — 1m Mini-AMD ที่ 50% Zone

เมื่อราคา retrace มาถึง 50% zone → เปิด chart 1m แล้วรอ mini-AMD

```
1m A  =  consolidation แถว 50% level  (หลายแท่ง 1m วิ่งซ้ายขวา)
1m M  =  wick เกิน A range เล็กน้อย    (ล่อ stop)
1m D  =  แท่งแรกที่ close ต่ำกว่า A floor  ← ✅ Entry SHORT
         แท่งแรกที่ close สูงกว่า A ceiling ← ✅ Entry LONG
```

---

### SL — Stop Loss
```
SHORT:  SL = 1m M wick สูงสุด + $10
LONG:   SL = 1m M wick ต่ำสุด − $10
```
**สำคัญ**: ใช้ 1m M wick ไม่ใช่ 15m M extreme — ทำให้ SL แคบและ RR สูงขึ้นมาก

---

### TP — Take Profit (Fibonacci Extension)
```
fib_leg = Bounce Top − MSS Low   (SHORT)
        = MSS High − Bounce Bot  (LONG)

TP1  =  Bounce Top/Bot  ∓  fib_leg × 3.5   (350%)
TP2  =  Bounce Top/Bot  ∓  fib_leg × 6.0   (600%)
TP3  =  Bounce Top/Bot  ∓  fib_leg × 8.0   (800%)
```

---

## ตัวอย่างเต็ม (SHORT)

```
Asian Range    : $103,100 – $104,800
M Extreme      : $105,200  (sweep เกิน $104,800)
RSI Divergence : ราคา high ขึ้น แต่ RSI ต่ำลง ✅

MSS Low        : $104,200  (low ต่ำสุดของ first leg)
fib_leg        : $104,700 − $104,200 = $500
Bounce Top     : $104,700  (50% retrace)

1m Entry       : $104,640  (1m D close ต่ำกว่า A floor)
SL             : $104,760  (1m M wick + $10)
Risk           : $120

TP1  350%      : $104,700 − $500 × 3.5 = $102,950   RR 1:19
TP2  600%      : $104,700 − $500 × 6.0 = $101,700   RR 1:25
TP3  800%      : $104,700 − $500 × 8.0 = $100,700   RR 1:33
```

---

## Position Sizing & Account

- **Exchange**: Crypto futures (Binance/Bybit/Pionex/อื่นๆ)
- **Per-trade margin**: ตามดุลพินิจ ขึ้นกับ budget ส่วนตัว
- **Leverage**: ตามดุลพินิจ — strategy นี้ทดสอบบน high leverage (50x+)
- **Fee**: 0.02–0.05% (taker) ขึ้นกับ exchange

> Account-specific config (margin, budget, leverage) → เก็บเป็น private notes ไม่ commit

## Universal Rules

- **Minimum fib_leg: $150** (สมดุลระหว่าง filter thin setups กับเก็บ signals ส่วนใหญ่ — target net ~$7 ที่ TP1)
- **Setup timeout: ไม่มี hard timeout** — setup ค้างได้นานถ้า structure ยังไม่เสีย (retrace ≤ 65%, ไม่มี M ใหม่) ตัดสินใจปิดเอง

---

## Checklist ก่อนเข้า Trade

```
□ Asian range > $200
□ มี M sweep เกิน Asian range
□ RSI Divergence confirm บน 15m
□ First leg (MSS) ชัดเจน
□ Bounce อยู่ใน 35-65% ของ first leg
□ 1m mini-AMD ครบ (A → M → D)
□ SL = เหนือ/ใต้ 1m M wick + $10
□ คำนวณ TP1/TP2/TP3 จาก fib_leg แล้ว
□ fib_leg ≥ $150
```

---

## Scripts — AMD

```bash
python3 ~/Documents/amd_full.py         # backtest 90 วัน
python3 ~/Documents/amd_full.py live    # เช็ค setup วันนี้
```

## Backtest Results — AMD (90 วัน, RSI swing div ON)

| Metric | ค่า |
|---|---|
| Signals | 16 |
| Win Rate | 31.2% (5W / 11L) |
| TP1 hit | 31% |
| TP2 hit | 19% |
| TP3 hit | 19% |
| Avg Risk | $267 |
| SHORT WR | 14% (uptrend period) |
| LONG WR | 44% |

---

---

# V+M Strategy — BTCUSDT Perpetual (Long Only)

## Overview
- **เหมาะกับ**: Uptrend / ขาขึ้น
- **Main TF**: 15m (structure) + 1m (entry)
- **Pattern**: V reversal + M กลับหัว (W = Double Bottom Higher Low)
- **Concept**: M ซ้อน M — 1m mini-AMD ซ้อนอยู่ใน 15m V+M structure

## Pattern Logic

```
V  = Sharp drop + recovery
     ราคา drop แรง → bounce กลับแรง

W  = Higher Low (M กลับหัว)
     หลัง V bounce → pullback → second low ที่สูงกว่า V

     V bot          W bot (HL)
      │               │
      ▼               ▼
  ────┴───────────────┴────
          Neckline ↑
```

## Full Setup Logic

### ① V Bottom
- ราคา drop จาก swing high อย่างน้อย **1.5%**
- Swing low = V bottom

### ② Neckline
- Swing high แรกหลัง V = **Neckline**
- V bounce ต้อง recover ≥ 30% ของ V height

### ③ W Second Bottom (Higher Low)
- Swing low แรกหลัง neckline
- W low **ต้องสูงกว่า V low** (Higher Low)
- W low ต้องอยู่ **ใต้ neckline**

### ④ RSI Bullish Divergence
- RSI ที่ W bottom **> RSI ที่ V bottom**
- = ราคา Lower Low แต่ RSI Higher Low → Bullish Div ✅

### ⑤ 1m Mini-AMD ที่ Neckline (M ซ้อน M)
```
Zone  = neckline ± $120
1m A  = consolidation ใน zone
1m M  = lowest wick ใน zone  (stop hunt ลงหลอก) → SL anchor
1m D  = close เกิน A ceiling → ✅ Entry LONG
```

### SL / TP
```
SL       = ใต้ 1m M wick − $10
fib_leg  = neckline − w_low
TP1 350% = neckline + fib_leg × 3.5
TP2 600% = neckline + fib_leg × 6.0
TP3 800% = neckline + fib_leg × 8.0
```

## ตัวอย่าง

```
V bottom   = $94,000
Neckline   = $97,500  (V height = $3,500)
W bottom   = $95,800  (Higher Low ✅)
fib_leg    = $97,500 − $95,800 = $1,700

1m Entry   = $97,650
SL         = $95,650  (risk $2,000)
TP1 350%   = $97,500 + $1,700 × 3.5 = $103,450  (RR ~3x)
TP2 600%   = $97,500 + $1,700 × 6.0 = $107,700  (RR ~5x)
TP3 800%   = $97,500 + $1,700 × 8.0 = $111,100  (RR ~7x)
```

## Checklist ก่อนเข้า V+M

```
□ V drop ≥ 1.5% จาก prior swing high
□ V bounce recover ≥ 30%
□ W second bottom เป็น Higher Low
□ W อยู่ใต้ neckline
□ RSI bullish divergence (W RSI > V RSI)
□ 1m mini-AMD ที่ neckline ครบ (A → M → D)
□ SL = ใต้ 1m M wick − $10
□ fib_leg ≥ $150
□ ตลาดเป็น uptrend (ดู context ภาพใหญ่)
```

## Scripts — V+M

```bash
python3 ~/Documents/vm_backtest.py         # backtest 90 วัน
python3 ~/Documents/vm_backtest.py live    # เช็ค setup ล่าสุด
```

## Backtest Results — V+M (90 วัน, RSI div ON)

| Metric | ค่า |
|---|---|
| Signals | 29 |
| Win Rate | 27.6% (8W / 21L) |
| TP1 hit | 28%  RR ~7.6x |
| TP2 hit | 17%  RR ~13x  |
| TP3 hit | 10%  RR ~17x  |
| Avg Risk | $276 |
| Avg fib_leg | $595 |

---

## ไฟล์ทั้งหมด

| ไฟล์ | หน้าที่ |
|---|---|
| `~/Documents/Trade.md` | Strategy doc นี้ |
| `~/Documents/amd_full.py` | AMD backtest + live |
| `~/Documents/vm_backtest.py` | V+M backtest + live |
| `~/Documents/.cache_1m_btcusdt.pkl` | Cache 1m data (shared, อายุ 4h) |
| `~/Documents/amd_full_results.csv` | AMD backtest results |
| `~/Documents/vm_results.csv` | V+M backtest results |

---

## สิ่งที่ต้องทำต่อ

- [x] กำหนด minimum fib_leg สำหรับทั้งสอง strategy → **$150**
- [x] พิจารณา position sizing → **$25 margin × 50x บน Pionex**
- [ ] เก็บ trade log จริงเพื่อ validate กับ backtest
- [ ] ต่อ API key สำหรับ auto mode (เมื่อพร้อม)
