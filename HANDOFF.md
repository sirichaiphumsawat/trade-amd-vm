# HANDOFF — sync remote work back to Mac

อ่านเอกสารนี้ก่อน pull ลง Mac เพื่อเข้าใจสิ่งที่เปลี่ยน + กันปัญหาที่อาจเกิด

---

## สรุปสิ่งที่ทำในรอบนี้ (26-30 พ.ค. 2026)

### Bugs ที่แก้
1. **Alert หาย 2 วัน** — script crash เงียบ + filter เข้มเกิน
2. **Exchange API blocked** — GH runner IP โดน geo-block ทั้ง 4 endpoints
3. **Instant stop-out** — V+M LONG SL บางแค่ $41 (0.06%) โดน noise เด้งทันที
4. **Crash ซ่อนเป็น no-setup** — `check_amd/check_vm` return None ทั้ง crash และ no-signal

### Files ที่เพิ่ม
- `exchange_utils.py` — shared 6-tier exchange fallback + SSL safe
- `context.md` — บริบทระบบทั้งหมด
- `AGENTS.md` — กฎสำหรับ AI agent
- `HANDOFF.md` — เอกสารนี้

### Files ที่แก้
- `amd_full.py` — ใช้ `exchange_utils.make_exchange()`, `USE_DIV=False`, min SL distance
- `vm_backtest.py` — เหมือนกัน
- `monitor_ci.py` — ใช้ exchange_utils, crash → Telegram alert, status report ทุก 30 นาที, ตัด stale filter
- `chart_setup.py` — ใช้ `exchange_utils.fetch_klines_raw / fetch_price`
- `daily_summary.py` — ใช้ `exchange_utils.fetch_ticker_24h`
- `.github/workflows/monitor.yml` — เพิ่ม schedule cron backup
- `Trade.md` — อัพเดต fib_leg $120, ระบุ filter ที่ปิด/ตัด

### Files ที่ลบ
- `amd_formation_analysis.png`, `amd_short_analysis.png`, `trading_plan_today.png` (test artifacts)

---

## ขั้นตอน Sync Mac

```bash
cd ~/Documents/trade-amd-vm   # หรือ path ที่ repo อยู่

# 1. Backup สิ่งที่อยู่บน Mac (เผื่อมี local changes)
git stash push -m "before-sync-$(date +%Y%m%d)" --include-untracked

# 2. Pull รวบทุก commit
git fetch origin master
git log HEAD..origin/master --oneline    # ดูว่ามีอะไรใหม่บ้าง
git pull --rebase origin master

# 3. ติดตั้ง deps (ถ้ามี module ใหม่)
pip3 install -r requirements.txt

# 4. ทดสอบ
python3 amd_full.py live           # ต้องไม่ error
python3 vm_backtest.py live        # ต้องไม่ error
python3 chart_setup.py --no-open   # ต้องสร้างกราฟได้

# 5. ถ้ามี stash ก่อนหน้า เช็คว่าจำเป็นไหม
git stash list
git stash show -p stash@{0}        # ดูว่ามีอะไรเก็บไว้
# ถ้าไม่ต้องการ: git stash drop
# ถ้าต้องการ:    git stash pop
```

---

## ปัญหาที่อาจเกิด + วิธีแก้

### 1. Merge conflict กับ bot commits
**อาการ**: `git pull --rebase` ล้มเหลวเพราะ `monitor_state.json` / `alerts_log.json` / `active_trades.json` ขัดแย้ง

**สาเหตุ**: GH Actions bot commit state ทุก 5-30 นาที — ถ้า Mac มี local change ในไฟล์เหล่านี้จะชนกัน

**แก้**:
```bash
# ใช้เวอร์ชันจาก remote เสมอ (bot คือ source of truth)
git checkout --theirs monitor_state.json alerts_log.json active_trades.json
git rebase --continue
```

### 2. Cache path ไม่ตรง
**อาการ**: `amd_full.py` พยายามเขียน cache ที่ `~/Documents/.cache_1m_btcusdt.pkl` แต่ไม่มี directory

**สาเหตุ**: hardcoded path ใน `amd_full.py:46`, `vm_backtest.py:51`

**แก้**: สร้าง directory `~/Documents/` ถ้ายังไม่มี หรือเปลี่ยน `CACHE_FILE` ให้ใช้ path ใน repo
```python
# ของเดิม
CACHE_FILE = os.path.expanduser('~/Documents/.cache_1m_btcusdt.pkl')
# ถ้าอยากเก็บใน repo (อย่าลืม .gitignore):
# CACHE_FILE = os.path.join(os.path.dirname(__file__), '.cache_1m_btcusdt.pkl')
```

### 3. Backtest WR ที่เห็นในอดีตอาจสูงเกินจริง
**สาเหตุ**: Backtest ใช้ 1m OHLC — ไม่จำลอง spread/wick ขนาดวินาที ส่งผลให้ SL บางๆ "รอด" ใน backtest แต่โดน stop ใน production

**แก้**: รัน backtest ใหม่ — Min SL fix จะทำให้ WR ใน backtest ลดลงเล็กน้อย แต่ตรงกับความจริงมากขึ้น
```bash
python3 amd_full.py            # backtest 90d ใหม่
python3 vm_backtest.py         # backtest 90d ใหม่
# เปรียบเทียบกับเลขเก่า (AMD 31.2%, V+M 27.6%)
```

### 4. RSI Divergence ปิดอยู่ — signal เยอะขึ้นมาก
**สาเหตุ**: ก่อนแก้ AMD ได้ 16 signals/90d (1 ทุก 5-6 วัน) — ปิด filter แล้วจะเยอะกว่าเดิม

**ผลกระทบ**: Telegram alert จะถี่ขึ้น คุณต้องเลือกเข้าเอง (ใช้ judgment + WR ของแต่ละทิศ)

**ทางเลือก**: ถ้าอยากเปิดกลับ
```python
# amd_full.py:40 และ vm_backtest.py:42
USE_DIV = True
```

### 5. ไฟล์ภาพ test ที่ลบไป
**สาเหตุ**: PNG 3 ไฟล์ที่ผมสร้างตอน demo ถูกลบออกจาก repo

**ผลกระทบ**: ไม่มี — เป็น artifacts ที่ regenerable ใหม่ได้ทุกเมื่อ

### 6. CF Worker secrets ยังเหมือนเดิม
**สาเหตุ**: ไม่ได้แตะ — secrets ยังอยู่บน Cloudflare ตามเดิม

**ตรวจสอบ**: ถ้าจำเป็นต้อง redeploy worker
```bash
cd worker
wrangler tail              # ดู log realtime
wrangler deployments list  # ดู deployment ล่าสุด
# ถ้าต้อง redeploy: wrangler deploy
```

---

## วิธีตรวจสอบว่า production ทำงานปกติ

### Telegram bot
- ส่ง `/status` ใน Telegram — ต้องตอบกลับ
- ส่ง `/price` — ต้องได้ราคา BTC ปัจจุบัน
- ส่ง `/check` — ต้อง trigger workflow + ตอบ confirmation
- รอ status report ทุก 30 นาที (ถ้าไม่มี setup)

### GH Actions
ไปที่ `github.com/sirichaiphumsawat/trade-amd-vm/actions/workflows/monitor.yml`
- ต้องเห็น runs ทุก 5 นาที (เขียวเป็นส่วนใหญ่)
- ถ้ามี run แดงต่อเนื่อง → คลิกดู log

### Bot state
```bash
git log --author="github-actions" --since="1 hour ago" --oneline
# ต้องมี commit ใหม่ภายใน 30 นาทีล่าสุด (status report) หรือ 5 นาที (มี active trade)
```

---

## Prompt สำหรับเปิด Claude Code session ใหม่บน Mac

```
ผมเปิดต่อจากที่ทำบน Claude Code on Web เมื่อ 26-30 พ.ค. 2026
อ่านไฟล์เหล่านี้ก่อนเริ่มงาน:
1. HANDOFF.md  - เอกสารส่งต่องาน
2. context.md  - บริบทระบบทั้งหมด
3. AGENTS.md   - กฎสำหรับ AI agent
4. Trade.md    - กลยุทธ์เต็ม

สรุปสั้นๆ:
- เป็น bot เทรด BTCUSDT, รัน 24/7 บน GH Actions, ส่ง alert ผ่าน Telegram
- เพิ่งแก้ bug ใหญ่ (alert หาย 2 วัน) + ปิด RSI div filter + เพิ่ม min SL distance
- Production ทำงานปกติแล้ว ยืนยันด้วย simulate alert + status report ทุก 30 นาที

งานที่ค้าง:
- รัน backtest ใหม่ (amd_full.py + vm_backtest.py) เพื่อวัด WR หลัง min SL fix
- ดูว่า WR ลดลงเท่าไร เทียบกับเก่า (AMD 31.2%, V+M 27.6%)
- ตัดสินใจว่า fib_leg $120 + min SL 20% ของ fib_leg = สมดุลหรือยัง

ห้าม:
- ตอบ 2 scenarios (SHORT + LONG) — ต้องเลือกทิศเดียว
- บอก "เสร็จแล้ว" ทั้งที่ยังไม่ตรงคำถาม
- เดาโดยไม่มีหลักฐาน — บอกตรงๆ ถ้าไม่รู้
```

---

## ของที่ยังไม่ทำ (Future work)

- [ ] Re-run backtest หลัง min SL fix เพื่อ validate WR ใหม่
- [ ] เก็บ real trade log เทียบกับ backtest (เคยมีใน Trade.md → still pending)
- [ ] ต่อ API key สำหรับ auto execution (ยังไม่พร้อม)
- [ ] พิจารณาเพิ่ม `max(fib_leg, current_volatility)` แทนการใช้ค่าคงที่ — adaptive SL
- [ ] ดู V+M signals หลังปิด RSI div ว่า WR เปลี่ยนยังไง
