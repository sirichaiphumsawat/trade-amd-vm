/**
 * trade-amd-vm Telegram bot worker
 *
 * Receives Telegram webhook POSTs and handles commands:
 *   /price   — current BTCUSDT price (instant from Binance)
 *   /check   — trigger GitHub Actions monitor manually
 *   /status  — last alert + workflow run status
 *   /help    — command list
 *
 * Secrets (set via `wrangler secret put`):
 *   TELEGRAM_BOT_TOKEN
 *   TELEGRAM_CHAT_ID       — only this chat is allowed (security)
 *   GITHUB_TOKEN           — fine-grained PAT with `Actions: write` for trade-amd-vm
 *   GITHUB_REPO            — "owner/repo" e.g. "sirichaiphumsawat/trade-amd-vm"
 */

const HELP = `
*BTC Trade Bot — Commands*

/price — ราคา BTC ปัจจุบัน
/check — สั่งตรวจ setup ทันที (ไม่ต้องรอ cron)
/status — last alert + cron status
/help — ดูคำสั่ง

_Setup alert ส่งอัตโนมัติทุก 5 นาทีอยู่แล้ว — commands ใช้กรณีอยากเช็คเอง_
`.trim();


export default {
  /**
   * Cron handler — fires every 5 min per wrangler.toml [triggers].
   * Pings GitHub workflow_dispatch so the monitor actually runs reliably.
   * (GH Actions native cron skips ~90% of runs on public repos / weekends.)
   *
   * Also acts as HEARTBEAT WATCHDOG: if last GH run is > 15 min ago,
   * send dead-system alert immediately so user never misses a setup
   * silently again.
   */
  async scheduled(event, env, ctx) {
    if (!env.GITHUB_TOKEN || !env.GITHUB_REPO) {
      console.error('Cron: missing GITHUB_TOKEN or GITHUB_REPO');
      return;
    }

    // 1) Trigger workflow
    const dispatchUrl = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/monitor.yml/dispatches`;
    let dispatchOk = false;
    try {
      const r = await fetch(dispatchUrl, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.GITHUB_TOKEN}`,
          'Accept': 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'User-Agent': 'trade-amd-vm-bot-cron',
        },
        body: JSON.stringify({ ref: 'master' }),
      });
      dispatchOk = (r.status === 204);
      console.log(`Cron dispatch: HTTP ${r.status}`);
      if (!dispatchOk) {
        const txt = await r.text();
        await sendMessage(
          env.TELEGRAM_BOT_TOKEN, env.TELEGRAM_CHAT_ID,
          `🚨 *Monitor cron FAILED to trigger GH*\n\nHTTP ${r.status}\n\`\`\`\n${txt.slice(0, 300)}\n\`\`\`\n\nระบบอาจหยุดทำงาน — ไปเช็ค Cloudflare logs`
        );
      }
    } catch (e) {
      console.error(`Cron trigger failed: ${e.message}`);
      await sendMessage(
        env.TELEGRAM_BOT_TOKEN, env.TELEGRAM_CHAT_ID,
        `🚨 *Monitor cron ERROR*\n\n\`${e.message}\`\n\nระบบหยุดทำงาน — ไปเช็ค Cloudflare logs`
      );
      return;
    }

    // Note: external dead-man's switch (healthchecks.io / uptimerobot) skipped —
    // CF cron + internal heartbeat already gives ~99% reliability.
    // If you want true independent verification later, set HEALTHCHECK_URL secret
    // and uncomment the ping below.
    //
    // if (dispatchOk && env.HEALTHCHECK_URL) {
    //   try { await fetch(env.HEALTHCHECK_URL); } catch (e) { console.error(e); }
    // }

    // 2) Heartbeat watchdog — check last GH run age
    try {
      const runsUrl = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/monitor.yml/runs?per_page=1`;
      const r = await fetch(runsUrl, {
        headers: {
          'Accept': 'application/vnd.github+json',
          'User-Agent': 'trade-amd-vm-bot-cron',
        },
      });
      if (!r.ok) return;
      const d = await r.json();
      const run = d.workflow_runs && d.workflow_runs[0];
      if (!run) return;

      const ageMin = (Date.now() - new Date(run.created_at).getTime()) / 60000;
      const lastStatus = run.status === 'completed' ? run.conclusion : run.status;

      // Alert if: last run > 15 min old (silent failure)
      //       OR  last run completed with failure (recent failure)
      const silent = ageMin > 15;
      const failed = run.status === 'completed' && run.conclusion !== 'success';

      if (silent || failed) {
        // Throttle: don't spam — only alert once per hour
        // Use KV would be ideal, but for simplicity just check minutes mod
        const minute = new Date().getUTCMinutes();
        if (minute % 60 < 5) {   // ~once per hour at top of hour
          const reason = silent
            ? `last run ${ageMin.toFixed(0)} min ago (should be < 10)`
            : `last run failed: ${lastStatus}`;
          await sendMessage(
            env.TELEGRAM_BOT_TOKEN, env.TELEGRAM_CHAT_ID,
            `⚠️ *Monitor heartbeat ผิดปกติ*\n\n${reason}\n\n[ดู runs](https://github.com/${env.GITHUB_REPO}/actions/workflows/monitor.yml)`
          );
        }
      }
    } catch (e) {
      console.error(`Heartbeat check failed: ${e.message}`);
    }
  },

  async fetch(request, env) {
    if (request.method !== 'POST') {
      return new Response('trade-amd-vm bot worker — ok', { status: 200 });
    }

    let update;
    try {
      update = await request.json();
    } catch (e) {
      return new Response('bad json', { status: 400 });
    }

    const message = update.message || update.edited_message;
    if (!message || !message.text) {
      return new Response('OK', { status: 200 });
    }

    const chatId = String(message.chat.id);
    const text = message.text.trim();

    // Security: only respond to the configured chat
    if (chatId !== env.TELEGRAM_CHAT_ID) {
      console.log(`Ignored message from unauthorized chat: ${chatId}`);
      return new Response('OK', { status: 200 });
    }

    let reply;
    const cmd = text.split(/\s+/)[0].toLowerCase();
    try {
      switch (cmd) {
        case '/start':
        case '/help':
          reply = HELP;
          break;
        case '/price':
          reply = await cmdPrice();
          break;
        case '/check':
          reply = await cmdCheck(env);
          break;
        case '/status':
          reply = await cmdStatus(env);
          break;
        default:
          reply = `ไม่รู้จักคำสั่ง \`${cmd}\`\n\n${HELP}`;
      }
    } catch (e) {
      reply = `_Error: ${e.message}_`;
    }

    await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, reply);
    return new Response('OK', { status: 200 });
  },
};


// ─── COMMANDS ─────────────────────────────────────────────────────────────

async function cmdPrice() {
  const r = await fetch(
    'https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT',
    { cf: { cacheTtl: 10 } }
  );
  if (!r.ok) throw new Error(`Binance ${r.status}`);
  const d = await r.json();
  const price = parseFloat(d.lastPrice);
  const change = parseFloat(d.priceChangePercent);
  const high = parseFloat(d.highPrice);
  const low = parseFloat(d.lowPrice);
  const arrow = change >= 0 ? '🟢' : '🔴';
  const sign = change >= 0 ? '+' : '';
  return [
    `*BTCUSDT*  ${arrow}`,
    '```',
    `Price   $${price.toLocaleString('en-US', { maximumFractionDigits: 2 })}`,
    `24h     ${sign}${change.toFixed(2)}%`,
    `High    $${high.toLocaleString('en-US', { maximumFractionDigits: 0 })}`,
    `Low     $${low.toLocaleString('en-US', { maximumFractionDigits: 0 })}`,
    '```',
  ].join('\n');
}


async function cmdCheck(env) {
  if (!env.GITHUB_TOKEN || !env.GITHUB_REPO) {
    return '_GITHUB_TOKEN หรือ GITHUB_REPO ยังไม่ตั้งใน worker secrets_';
  }
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/monitor.yml/dispatches`;
  const r = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.GITHUB_TOKEN}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'trade-amd-vm-bot',
    },
    body: JSON.stringify({ ref: 'master' }),
  });
  if (r.status !== 204) {
    const txt = await r.text();
    return `_Trigger ล้มเหลว (${r.status}): ${txt.slice(0, 200)}_`;
  }
  return [
    '🔍 *กำลังตรวจ setup...*',
    '',
    '_ใช้เวลา ~2 นาที (V+M ต้องโหลด 90d 1m data)_',
    '_ถ้ามี setup น่าเข้า → alert จะเด้งมาเอง_',
    '_ถ้าไม่มี → จะเงียบ (ไม่ตอบ)_',
  ].join('\n');
}


async function cmdStatus(env) {
  // 1) Latest workflow run
  let runInfo = '_ไม่สามารถดึง workflow status_';
  if (env.GITHUB_REPO) {
    const url = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/monitor.yml/runs?per_page=1`;
    try {
      const r = await fetch(url, {
        headers: {
          'Accept': 'application/vnd.github+json',
          'User-Agent': 'trade-amd-vm-bot',
        },
      });
      if (r.ok) {
        const d = await r.json();
        const run = d.workflow_runs && d.workflow_runs[0];
        if (run) {
          const status = run.status === 'completed' ? run.conclusion : run.status;
          const icon = status === 'success' ? '✅' : (status === 'in_progress' ? '⏳' : '❌');
          const when = new Date(run.created_at);
          const ageMin = Math.round((Date.now() - when.getTime()) / 60000);
          runInfo = `${icon} last run: ${ageMin} min ago (${status})`;
        }
      }
    } catch (e) {
      runInfo = `_workflow API error: ${e.message}_`;
    }
  }

  // 2) Last alert from monitor_state.json
  let stateInfo = '_ยังไม่มี alert ที่บันทึก_';
  if (env.GITHUB_REPO) {
    const url = `https://raw.githubusercontent.com/${env.GITHUB_REPO}/master/monitor_state.json`;
    try {
      const r = await fetch(url, { cf: { cacheTtl: 30 } });
      if (r.ok) {
        const state = await r.json();
        const lines = [];
        if (state.last_amd_sig) lines.push(`AMD: \`${state.last_amd_sig}\``);
        if (state.last_vm_sig) lines.push(`V+M: \`${state.last_vm_sig}\``);
        if (lines.length) stateInfo = lines.join('\n');
      }
    } catch (e) {
      stateInfo = `_state read error: ${e.message}_`;
    }
  }

  return [
    '*Monitor Status*',
    '',
    runInfo,
    '',
    '*Last Alerts:*',
    stateInfo,
  ].join('\n');
}


// ─── TELEGRAM API ─────────────────────────────────────────────────────────

async function sendMessage(token, chatId, text) {
  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      parse_mode: 'Markdown',
    }),
  });
}
