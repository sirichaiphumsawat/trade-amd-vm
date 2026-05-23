# Claude Bootstrap Prompt — BTC Trading Project

ใช้ prompt นี้ paste ตอนเปิด Claude Code session ใหม่ (หรือเครื่องใหม่) เพื่อให้ Claude เข้าใจ project ทันทีโดยไม่ต้องอธิบายซ้ำ

---

## 📋 Prompt (copy ทั้งหมดด้านล่าง)

```
นี่คือโปรเจ็คเทรด BTCUSDT Perpetual บน Pionex Futures ใช้ 2 กลยุทธ์คู่กัน (AMD + V+M)

อ่านไฟล์ทั้งหมดก่อนตอบ:
- README.md
- Trade.md (strategy เต็ม)
- amd_full.py, vm_backtest.py, chart_setup.py

Account context:
- ผม trade crypto futures บน high leverage (50x+) — รายละเอียด budget/margin เก็บไว้ส่วนตัว
- ถ้าผมบอก margin/budget ตอน chat ให้จำใน session แต่ห้ามเขียนลง repo

Rules ที่ต้องจำ:
1. fib_leg minimum = $150 (filter thin setups)
2. TP ต้องโชว์ครบ 3 อันเสมอ: 350% / 600% / 800% (ห้ามรายงาน TP เดียว)
3. Setup timeout: ไม่มี hard timeout — ค้างได้ถ้า structure ยังไม่เสีย (retrace ≤ 65%, ไม่มี M ใหม่)
4. SL ใช้ 1m M wick ± $10 (ไม่ใช่ 15m M extreme)
5. ตอบเป็นภาษาไทยเสมอ ยกเว้น code/terminal

Report layout (Checklist-first):
- ขึ้น checklist ก่อน → verdict → entry/SL/TP → warnings
- ดู README.md section "Report Layout" สำหรับ template
- ห้ามรายงาน entry/SL/TP ก่อน verdict

Workflow เวลาผมถาม "เข้าได้ไหม":
1. รัน: python3 amd_full.py live
2. รัน: python3 vm_backtest.py live
3. รัน: python3 chart_setup.py (สำหรับ AMD chart)
4. รายงานด้วย Checklist-first layout
5. โชว์ทั้ง text + ภาพ (chart_setup.py จะเปิด Preview เอง)

อย่าสรุปว่า "เข้าได้" ถ้า amd_full.py ไม่ออก signal — แม้ structure จะดูครบ

Pending work:
- เก็บ trade log จริงเพื่อ validate กับ backtest
- ต่อ API key สำหรับ auto mode (เมื่อพร้อม)
```

---

## 📁 Setup บนเครื่องใหม่

```bash
# 1. Clone
git clone https://github.com/sirichaiphumsawat/trade-amd-vm.git
cd trade-amd-vm

# 2. Install dependencies
pip3 install -r requirements.txt

# 3. Test
python3 amd_full.py live      # ต้องไม่ error
python3 chart_setup.py         # ต้องเปิด Preview ได้ (macOS)
```

## 🔍 Quick Reference

### Strategy Map
- **AMD SHORT/LONG**: ตลาด range หรือ sweep ชัด
- **V+M LONG**: ตลาด uptrend (V reversal + W pattern higher low)

### Detection (AMD)
- Asian range: 00:00-08:00 UTC
- M (Manipulation): high หลัง 08:00 ที่ sweep เกิน Asian high (SHORT) / low ใต้ Asian low (LONG)
- MSS Low/High: low/high ต่ำสุด/สูงสุดใน **16 แท่ง 15m แรกหลัง M** (เคร่งครัด)
- Bounce: ใน 35-65% retrace zone หลัง MSS
- Entry trigger: 1m mini-AMD A→M→D ที่ bounce zone

### Detection (V+M)
- V bottom: drop ≥ 1.5% จาก swing high
- Neckline: swing high หลัง V, bounce recover ≥ 30% V height
- W bottom: Higher Low, ใต้ neckline, RSI bullish div
- Entry trigger: 1m mini-AMD ที่ neckline ± $120
