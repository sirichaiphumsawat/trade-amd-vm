# Context — trade-amd-vm

## ระบบนี้คืออะไร

Bot ตรวจจับโอกาสเทรด BTCUSDT Perpetual อัตโนมัติ 24/7 ส่ง alert พร้อม entry/SL/TP ผ่าน Telegram เมื่อพบ setup ที่ผ่านเกณฑ์ ใช้ 2 กลยุทธ์: AMD และ V+M

---

## สถาปัตยกรรม

```
Cloudflare Worker cron (ทุก 5 นาที)
  │
  ▼ POST workflow_dispatch
GitHub Actions (ubuntu-latest)
  │
  ├─ python amd_full.py live    ← AMD detection (rule-based, ไม่มี AI)
  ├─ python vm_backtest.py live ← V+M detection (rule-based, ไม่มี AI)
  ├─ chart_setup.py             ← สร้างกราฟแนบ alert
  │
  ▼ monitor_ci.py
  ├─ parse stdout → ตรวจ entry/SL/TP
  ├─ dedup (signature ไม่ซ้ำ)
  ├─ fib_leg >= $120
  ├─ format_alert → Telegram
  ├─ check_hits → SL/TP hit detection
  └─ commit state → git push master

Backup: GH Actions schedule cron */5 (ไม่เสถียร 100% แต่เป็น fallback)
```

### ไฟล์สำคัญ

| ไฟล์ | หน้าที่ |
|---|---|
| `exchange_utils.py` | Shared module — 6-tier exchange fallback + SSL safe |
| `amd_full.py` | AMD strategy: detect + backtest + live check |
| `vm_backtest.py` | V+M strategy: detect + backtest + live check |
| `monitor_ci.py` | Orchestrator: รัน detection, ส่ง Telegram, track state |
| `chart_setup.py` | สร้างกราฟ dark theme (mplfinance) แนบ alert |
| `daily_summary.py` | สรุปรายวัน 07:00 ไทย |
| `Trade.md` | เอกสารกลยุทธ์เต็ม + checklist |
| `worker/src/index.js` | CF Worker: cron trigger + Telegram bot commands |

### State files (GH Actions commit กลับ master)

| ไฟล์ | หน้าที่ |
|---|---|
| `monitor_state.json` | dedup signatures + last status report timestamp |
| `alerts_log.json` | ประวัติ alert 90 วัน |
| `active_trades.json` | trade ที่เปิดอยู่ (SL/TP tracking) |

---

## กลยุทธ์

### AMD (Accumulation / Manipulation / Distribution)

ทิศ: SHORT หรือ LONG (วันละ 1 ทิศ ขึ้นกับว่า M sweep ทางไหน)

1. **A** (00:00-08:00 UTC): สร้าง Asian Range (H/L) — range > $200
2. **M** (08:00-13:00 UTC): ราคา sweep เกิน Asian H (SHORT) หรือ L (LONG)
3. **MSS**: First leg — หา extreme ใน 16 แท่ง 15m หลัง M
4. **Fib 50%**: Retrace 35-65% ของ first leg
5. **Entry**: 1m mini-AMD ที่ 50% zone (A→M→D บน 1m)
6. **SL**: 1m M wick ± $10
7. **TP**: 350% / 600% / 800% ของ fib_leg

### V+M (V Reversal + W Double Bottom)

ทิศ: LONG เท่านั้น

1. **V**: Drop ≥ 1.5% จาก swing high → bounce recover ≥ 30%
2. **Neckline**: Swing high แรกหลัง V
3. **W**: Second bottom เป็น Higher Low (สูงกว่า V low)
4. **Entry**: 1m mini-AMD ที่ neckline ± $120
5. **SL**: ใต้ 1m M wick − $10
6. **TP**: neckline + fib_leg × 3.5/6.0/8.0

---

## Filter ปัจจุบัน (26 พ.ค. 2026)

| Filter | ค่า | สถานะ |
|---|---|---|
| Asian Range | > $200 | เปิด |
| RSI Divergence | `USE_DIV` | **ปิด** (เคยกรองออกเกือบทุกวัน) |
| Bounce Retrace | 35-65% | เปิด |
| 1m mini-AMD | ≥ 3 candles ใน zone | เปิด |
| fib_leg | ≥ $120 | เปิด (ลดจาก $150) |
| Stale timer | - | **ตัดออก** |
| Min SL distance | `max(fib_leg × 20%, $80)` | เปิด — กัน instant stop จาก noise |
| Dedup | signature ไม่ซ้ำ | เปิด |

---

## Exchange Fallback Chain

`exchange_utils.py` — ทุกสคริปต์เรียกใช้ shared module นี้

```
1. binanceusdm (ccxt)     ← preferred
2. binance spot (ccxt)     ← ถ้า futures โดนบล็อก
3. bybit (ccxt)            ← infra ต่างจาก Binance
4. data-api.binance.vision ← public endpoint, raw HTTP
5. bybit v5 API            ← raw HTTP
6. okx v5 API              ← raw HTTP
```

- จับ **ทุก exception** แล้ว continue (ไม่ raise)
- SSL fallback: ถ้า cert verify ไม่ผ่าน retry แบบ unverified
- ทดสอบ `fetch_ohlcv` จริงก่อนยืนยันว่าใช้ได้

---

## Telegram Alerts

### Setup alert (เมื่อพบ signal)
```
🚨 AMD SHORT — ready
BTCUSDT 15m · 14:30 UTC (21:30 ไทย)

Entry   $77,000
SL      $77,660
─────────────────────────
TP1   $72,800  ↓4,200  1:6.4
TP2   $69,800  ↓7,200  1:10.9
TP3   $67,400  ↓9,600  1:14.5
─────────────────────────
fib_leg $1,200   ✓ pass
WR 90d  14%  (AMD SHORT)
```

### Status report (ทุก 30 นาทีถ้าไม่มี setup)
```
📊 Status  03:00 UTC (10:00 TH)
BTC    $77,293  (+0.3%)
H/L    $77,500 / $76,700
Phase  A
AMD    no setup
V+M    no setup
```

### Crash alert (ถ้า script พัง)
```
⚠️ AMD script crash
rc=1
[error message]
```

### Hit alert (SL/TP ถูก)
```
✅ TP1 HIT — AMD SHORT
BTCUSDT · 16:00 UTC (23:00 ไทย)
Hit     $72,800
Entry   $77,000
P&L     +4,200  (+5.45%)
RR      +1:6.4
```

---

## Cloudflare Worker Commands (Telegram)

| Command | หน้าที่ |
|---|---|
| `/price` | ราคา BTC ปัจจุบัน |
| `/check` | trigger detection ทันที |
| `/status` | last alert + GH Actions run status |
| `/help` | รายการคำสั่ง |

---

## กฎสำคัญ

1. **ไม่มี AI/Claude ใน pipeline** — ทุกอย่าง rule-based Python scripts
2. **ทิศเดียวต่อวัน** สำหรับ AMD — ขึ้นกับว่า M sweep ทางไหน
3. **V+M เกิดได้ทุกเวลา** ไม่ขึ้นกับ session
4. **ห้ามเงียบ** — crash ต้องส่ง Telegram, ไม่มี setup ก็ส่ง status ทุก 30 นาที
5. **Chart สไตล์ chart_setup.py** — dark theme, mplfinance, mark RB/Entry/MSS/M/TP

---

## ปัญหาที่เคยเจอและแก้แล้ว (26 พ.ค. 2026)

| ปัญหา | สาเหตุ | แก้ |
|---|---|---|
| Alert ไม่มา 2 วัน | script crash เงียบ + filter เข้ม | exchange_utils + crash alert + ปิด RSI div + ตัด stale |
| Exchange API blocked | GH runner IP โดน geo-block | 6-tier fallback chain |
| Crash ซ่อนเป็น "no setup" | `check_amd()` return None ทั้ง crash และ no-setup | crash → `telegram_send` แจ้ง |
| RSI div กรองเกิน | 16 signals ใน 90 วัน | `USE_DIV = False` |
| Stale timer ข้าม signal | V+M entry > 30 นาที = skip | ตัดออกทั้งหมด |
| Chart ไม่มี fallback | `chart_setup.py` hardcode fapi.binance.com | ใช้ `exchange_utils.fetch_klines_raw` |
| GH cron ไม่เสถียร | GH Actions skip 90% on weekends | CF Worker cron + GH cron backup |

---

## Development

```bash
# Local
python3 amd_full.py live       # เช็ค AMD วันนี้
python3 vm_backtest.py live    # เช็ค V+M
python3 chart_setup.py         # สร้างกราฟ
python3 amd_full.py            # backtest 90d
python3 vm_backtest.py         # backtest 90d

# Deploy CF Worker
cd worker
wrangler deploy
wrangler secret put GITHUB_TOKEN   # fine-grained PAT, Actions: write
wrangler secret put TELEGRAM_BOT_TOKEN
wrangler secret put TELEGRAM_CHAT_ID
wrangler secret put GITHUB_REPO    # sirichaiphumsawat/trade-amd-vm
wrangler tail                      # ดู log realtime
```
