# trade-amd-vm Telegram Bot Worker

Cloudflare Worker ที่รับ Telegram webhook และตอบ commands:

| Command | หน้าที่ |
|---|---|
| `/help` | รายการคำสั่ง |
| `/price` | ราคา BTCUSDT ปัจจุบัน (instant) |
| `/check` | สั่งตรวจ setup ทันที (trigger GH Actions) |
| `/status` | last alert + cron status |

> Alert auto ทุก 5 นาทียัง work เหมือนเดิม — bot นี้ใช้กรณีอยากเช็คเอง

---

## Deploy

### 1. ติดตั้ง wrangler CLI
```bash
npm install -g wrangler
wrangler login   # เปิด browser ให้ login Cloudflare
```

### 2. ตั้ง secrets
```bash
cd ~/Developer/trade-amd-vm/worker

wrangler secret put TELEGRAM_BOT_TOKEN
# วางค่า bot token

wrangler secret put TELEGRAM_CHAT_ID
# วาง 8594235472

wrangler secret put GITHUB_REPO
# วาง sirichaiphumsawat/trade-amd-vm

wrangler secret put GITHUB_TOKEN
# วาง fine-grained PAT (สร้างที่ https://github.com/settings/tokens?type=beta)
# Repository: trade-amd-vm
# Permissions: Actions → Read and write
```

### 3. Deploy
```bash
wrangler deploy
```
จะได้ URL แบบ `https://trade-amd-vm-bot.<your-subdomain>.workers.dev`

### 4. ตั้ง Telegram webhook
แทน `<URL>` ด้วย URL ที่ได้, `<TOKEN>` ด้วย bot token:
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<URL>"
```

ลองส่ง `/help` ใน Telegram → bot ต้องตอบ

---

## Logs
```bash
wrangler tail   # stream logs realtime
```

## Update
```bash
wrangler deploy   # หลังแก้ src/index.js
```
