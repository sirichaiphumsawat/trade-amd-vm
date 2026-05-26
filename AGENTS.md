# AGENTS.md — trade-amd-vm

## โปรเจกต์นี้คืออะไร

Bot เทรด BTCUSDT Perpetual อัตโนมัติ ตรวจจับ setup ทุก 5 นาทีแล้วส่ง Telegram alert พร้อม entry/SL/TP
ใช้ 2 กลยุทธ์ rule-based (ไม่มี AI ใน pipeline): AMD และ V+M

## กฎที่ต้องปฏิบัติ

### เมื่อผู้ใช้ถาม "น่าเทรดไหม" หรือ "เข้าได้ไหม"

1. อ่าน `Trade.md` และ `context.md` ก่อนทำอะไรทั้งนั้น
2. ดึงราคา BTC จริง — ใช้ exchange API ถ้าต่อได้ ใช้ WebSearch ถ้าต่อไม่ได้
3. ระบุ session ปัจจุบัน (A/M/D) จากเวลา UTC
4. วิเคราะห์ **ทิศเดียว** ตาม AMD framework — ไม่ให้ 2 scenario
5. สร้างกราฟสไตล์ `chart_setup.py` (mplfinance dark theme, mark RB/Entry/MSS/M/TP)
6. ส่งผลวิเคราะห์ + กราฟ ครั้งเดียวจบ

### ห้าม

- ห้ามส่ง 2 scenario (SHORT + LONG) — ตัดสินใจทิศเดียว
- ห้ามบอก "ใช้ได้" หรือ "เสร็จแล้ว" ถ้ายังไม่ตรงกับคำถาม
- ห้ามเดาโดยไม่มีหลักฐาน — ถ้าไม่รู้ให้บอกตรงๆ
- ห้ามวนลูปลอง API ที่ใช้ไม่ได้ — ใช้ WebSearch แทนถ้า exchange API blocked
- ห้ามสร้าง timeline chart หรือ infographic ที่ไม่มีใครขอ
- ห้ามเขียน budget/margin/leverage ลง repo

### ต้องทำ

- อ่าน repo (Trade.md, context.md, chart_setup.py) ก่อนเริ่มงานทุกครั้ง
- ตอบภาษาไทย ยกเว้น code
- TP โชว์ครบ 3 อัน: 350% / 600% / 800%
- SL ใช้ 1m M wick ± $10 (ไม่ใช่ 15m M extreme)
- กราฟใช้สไตล์ chart_setup.py — dark theme, RB zone, Entry zone, phase labels

## สถาปัตยกรรม

```
CF Worker cron (5 min) → GH Actions workflow_dispatch → monitor_ci.py
                                                           ├─ amd_full.py live
                                                           ├─ vm_backtest.py live
                                                           ├─ chart_setup.py (chart)
                                                           ├─ check_hits (SL/TP tracking)
                                                           └─ Telegram alert
```

Backup: GH Actions schedule cron `*/5 * * * *`

## ไฟล์และหน้าที่

| ไฟล์ | หน้าที่ | แก้บ่อย |
|---|---|---|
| `exchange_utils.py` | 6-tier exchange fallback ใช้ร่วมทุกสคริปต์ | ไม่ค่อย |
| `amd_full.py` | AMD detection + backtest | เมื่อปรับ filter |
| `vm_backtest.py` | V+M detection + backtest | เมื่อปรับ filter |
| `monitor_ci.py` | Orchestrator: detection → Telegram → state | บ่อย |
| `chart_setup.py` | กราฟ dark theme (mplfinance) | เมื่อปรับ UI |
| `daily_summary.py` | สรุปรายวัน 07:00 ไทย | ไม่ค่อย |
| `worker/src/index.js` | CF Worker: cron + Telegram commands | ไม่ค่อย |
| `Trade.md` | เอกสารกลยุทธ์เต็ม | เมื่อเปลี่ยนกลยุทธ์ |
| `context.md` | บริบทระบบทั้งหมด | เมื่อเปลี่ยนระบบ |
| `.github/workflows/monitor.yml` | GH Actions workflow | เมื่อเปลี่ยน pipeline |

## Filter ปัจจุบัน

| Filter | ค่า | หมายเหตุ |
|---|---|---|
| Asian Range | > $200 | กรอง range แคบ |
| RSI Divergence | **ปิด** | เคยกรองหนักเกิน |
| Bounce Retrace | 35-65% | |
| 1m mini-AMD | ≥ 3 candles | |
| fib_leg | ≥ $120 | ลดจาก $150 |
| Stale timer | **ตัดออก** | เคยข้าม signal เก่า |

## Telegram behavior

- **มี setup** → ส่ง alert ทันที พร้อม chart
- **ไม่มี setup** → ส่ง status report ทุก 30 นาที (ราคา + phase + ผล detection)
- **Script crash** → ส่ง error alert ทันที
- **SL/TP hit** → ส่ง hit alert พร้อม P&L

## Exchange fallback

`exchange_utils.py` — ลำดับ:
1. binanceusdm (ccxt)
2. binance spot (ccxt)
3. bybit (ccxt)
4. data-api.binance.vision (raw HTTP)
5. bybit v5 (raw HTTP)
6. okx v5 (raw HTTP)

จับทุก exception → continue ถัดไป (ไม่ raise)
SSL fallback อัตโนมัติ

## ปัญหาที่เคยเจอ

| ปัญหา | สาเหตุ | บทเรียน |
|---|---|---|
| Alert หาย 2 วัน | script crash เงียบ + filter เข้ม | ห้ามซ่อน error เป็น "no setup" |
| Exchange blocked | GH runner IP โดน geo-block | ต้องมี fallback หลายตัว + จับทุก exception |
| RSI div กรองเกิน | 16 signals ใน 90 วัน | Filter ที่เข้มเกินอันตรายกว่าไม่มี filter |
| สับสน crash vs no-setup | ทั้งคู่ return None | crash ต้องส่ง Telegram แจ้ง |
| Claude ให้ 2 scenario | ไม่ตัดสินใจ | ต้องวิเคราะห์แล้วระบุทิศเดียว |
| Claude บอก "เสร็จ" ทั้งที่ไม่ตรง | ไม่ตรวจสอบก่อนตอบ | ห้ามบอก "ใช้ได้" ถ้ายังไม่ตรงคำถาม |

## วิธีทดสอบ

```bash
# Local
python3 amd_full.py live       # AMD วันนี้
python3 vm_backtest.py live    # V+M
python3 chart_setup.py         # กราฟ
python3 amd_full.py            # backtest 90d

# E2E test (trigger simulate alert)
# GitHub → Actions → Trade Monitor → Run workflow → simulate: true

# CF Worker
cd worker && wrangler tail     # ดู cron log
```

## Session context

- เวลาไทย = UTC + 7
- Asian session: 07:00-15:00 ไทย (สร้าง range)
- London session: 15:00-20:00 ไทย (M sweep — จุดสำคัญ)
- NY session: 20:00-00:00 ไทย (Distribution — entry zone)
