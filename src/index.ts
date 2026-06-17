import type { Env, TgUpdate, TgMessage } from './types';
import { makeStore, Store } from './store';
import { Telegram } from './telegram';
import { isAdmin } from './moderation';
import { ensureVerified } from './verify';
import { classifyMessage, shouldIntercept } from './ai-filter';
import { makeRelay } from './relay';
import { handleAdminMessage } from './admin';
import { handleDraftCallback } from './assistant';
import { handleGroupAiMessage } from './group-ai';
import { isFromTelegram, verifyBotSecret, verifyWebhookSecret } from './security';
import { sanitizeForLog } from './sanitize';

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === '/health') return new Response('ok');

    // FIX B32: /stats diagnostic endpoint (admin-only) for quick health checks.
    // Returns basic info without exposing sensitive data.
    if (url.pathname === '/stats') {
      if (!verifyBotSecret(request, env, url)) {
        return new Response('forbidden', { status: 403 });
      }
      const store = makeStore(env);
      const intercepted = await store.getInterceptedIndex(1);
      const audit = await store.getAuditLog(1);
      const stats = {
        ok: true,
        time: new Date().toISOString(),
        has_intercepts: intercepted.length > 0,
        has_audit: audit.length > 0,
        admin_uid_configured: !!env.ADMIN_UID,
        ai_base_url_configured: !!env.AI_BASE_URL,
        ai_api_key_configured: !!env.AI_API_KEY,
        search_api_key_configured: !!env.SEARCH_API_KEY,
        filter_enabled: (env.FILTER_ENABLED ?? 'true') === 'true',
        group_ai_enabled: (env.GROUP_AI_ENABLED ?? 'false') === 'true',
        active_model: (await store.getActiveModel()) || env.AI_MODEL || '(none)',
        admin_ai_mode: await store.getAdminAiMode(),
      };
      return new Response(JSON.stringify(stats, null, 2), {
        headers: { 'content-type': 'application/json' },
      });
    }

    // ---- Management endpoints ----
    // SECURITY FIX (H6): all management endpoints accept POST + x-bot-secret header
    // (GET with ?secret= still works as legacy fallback, but is logged as warning)

    if (url.pathname === '/setcommands') {
      if (request.method !== 'POST') {
        return new Response('method not allowed — use POST with x-bot-secret header', { status: 405 });
      }
      if (!verifyBotSecret(request, env, url)) return new Response('forbidden', { status: 403 });
      const tg = new Telegram(env.BOT_TOKEN);
      await tg.setMyCommands([{ command: 'start', description: '开始使用 / 重新验证' }], { type: 'default' });
      const adminCommands = [
        { command: 'ai', description: '与AI助理对话；reply转发消息则按意向代笔' },
        { command: 'model', description: '查看/切换模型：list 列表，<名字> 切换，default 恢复' },
        { command: 'aimode', description: 'AI 模式开关：on 开启普通消息直聊，off 退出' },
        { command: 'to', description: '主动给用户发消息：/to <uid> 内容' },
        { command: 'intercepts', description: '查看最近拦截记录' },
        { command: 'audit', description: '查看管理员审计日志' },
        { command: 'ban', description: '封禁用户（reply转发消息或带uid）' },
        { command: 'unban', description: '解封用户（reply转发消息或带uid）' },
        { command: 'forgive', description: '清空用户误伤/违规计数（reply或带uid）' },
      ];
      if (env.ADMIN_UID) {
        await tg.setMyCommands(adminCommands, { type: 'chat', chat_id: Number(env.ADMIN_UID) });
      }
      return new Response('✅ commands set (public: start; admin: full menu)');
    }

    if (url.pathname === '/registerWebhook') {
      if (request.method !== 'POST') {
        return new Response('method not allowed — use POST with x-bot-secret header', { status: 405 });
      }
      if (!verifyBotSecret(request, env, url)) return new Response('forbidden', { status: 403 });
      const tg = new Telegram(env.BOT_TOKEN);
      // FIX B21: support WEBHOOK_URL_OVERRIDE for local dev / tunnels (e.g. ngrok).
      // Falls back to the request's own origin, which works in production.
      const hookUrl = env.WEBHOOK_URL_OVERRIDE
        ? `${env.WEBHOOK_URL_OVERRIDE.replace(/\/$/, '')}/webhook`
        : `${url.origin}/webhook`;
      await tg.setWebhook(hookUrl, env.BOT_SECRET);
      return new Response(`✅ webhook set to ${hookUrl}`);
    }

    if (url.pathname === '/unregisterWebhook') {
      if (request.method !== 'POST') {
        return new Response('method not allowed — use POST with x-bot-secret header', { status: 405 });
      }
      if (!verifyBotSecret(request, env, url)) return new Response('forbidden', { status: 403 });
      await new Telegram(env.BOT_TOKEN).deleteWebhook();
      return new Response('✅ webhook deleted');
    }

    if (url.pathname === '/webhook' && request.method === 'POST') {
      // SECURITY FIX (M12): verify Telegram ASN via cf.asn (unless bypassed in dev)
      if (!isFromTelegram(request, env)) {
        return new Response('forbidden: not from telegram', { status: 403 });
      }
      // SECURITY FIX: constant-time comparison via verifyWebhookSecret
      if (!verifyWebhookSecret(request, env)) {
        return new Response('forbidden', { status: 403 });
      }
      // FIX P40: parse JSON safely — non-JSON body shouldn't crash the Worker.
      let update: TgUpdate;
      try {
        update = (await request.json()) as TgUpdate;
      } catch (e) {
        console.warn('webhook: non-JSON body', (e as Error).message);
        return new Response('bad request', { status: 400 });
      }
      // Defensive: validate update_id is a finite integer
      if (!Number.isFinite(update?.update_id)) {
        return new Response('bad request', { status: 400 });
      }
      // FIX B4: dedupe in the main fetch (synchronous) BEFORE ctx.waitUntil,
      // so concurrent retries from Telegram cannot both pass the seenUpdate check.
      const store = makeStore(env);
      if (await store.seenUpdate(update.update_id)) {
        return new Response('ok');
      }
      // FIX P-anti-brute: per-IP rate limit backstop. Telegram uses ~10 IP
      // ranges, so 200/hour is generous for legit traffic but stops flooding.
      // We pass the IP to handleUpdate via env-like context (not on env itself
      // to avoid type churn); instead we read it inside handleUpdate from
      // the request again. Simpler: pass it as a closure.
      const clientIp = request.headers.get('CF-Connecting-IP') || 'unknown';
      // Pass IP via closure
      ctx.waitUntil(
        handleUpdate(update, env, clientIp).catch((e) =>
          console.error('handleUpdate error', (e as Error).message),
        ),
      );
      return new Response('ok');
    }

    if (url.pathname === '/webhook') {
      // FIX P41: GET /webhook should return 405, not fall through.
      return new Response('method not allowed', { status: 405 });
    }

    return new Response('nicechat-bot', { status: 200 });
  },
} satisfies ExportedHandler<Env>;

async function handleUpdate(update: TgUpdate, env: Env, clientIp: string): Promise<void> {
  const store = makeStore(env);
  const tg = new Telegram(env.BOT_TOKEN);

  // FIX R2: admin bypasses IP rate limit. Previously admin and normal users
  // shared the 200/hour IP budget, so on a shared network (home/office) normal
  // users could exhaust the budget and lock out the admin. Admin is trusted
  // and has its own (no) per-user rate limit, so we skip IP check for admin.
  // We still apply IP limit to non-admin paths to prevent flooding.

  // FIX B4: seenUpdate is now checked in the main fetch handler before
  // ctx.waitUntil, so we don't re-check here. (KV eventual consistency
  // means rare duplicates may still occur — acceptable for personal bots.)

  if (update.callback_query) {
    const callback = update.callback_query;
    // FIX B3: reject callbacks from bots (defensive — Telegram shouldn't send these)
    if (callback.from.is_bot) {
      await tg.answerCallbackQuery(callback.id, '拒绝').catch(() => {});
      return;
    }
    if (!isAdmin(env, callback.from.id)) {
      await tg.answerCallbackQuery(callback.id, '无权限');
      return;
    }
    const data = callback.data ?? '';
    const messageId = callback.message?.message_id;
    // FIX B3: callback_data is limited to 64 bytes by Telegram. Our draftId
    // format `${userId}-${Date.now().toString(36)}-${crypto.randomUUID().slice(0,8)}`
    // is well under 64 bytes for any realistic userId and timestamp.
    const match = data.match(/^draft:(send|regen|manual):(.+)$/);
    if (match && messageId) {
      await tg.answerCallbackQuery(callback.id, '处理中…');
      await handleDraftCallback(match[1], match[2], messageId, env, store, tg);
      return;
    }
    await tg.answerCallbackQuery(callback.id, '未知操作');
    return;
  }

  const msg = update.message ?? update.edited_message;
  if (!msg || !msg.from || msg.from.is_bot) return;

  // SECURITY FIX (H7): edited messages get a lightweight path — no verification,
  // no rate limit, no AI filter, no relay. They are essentially ignored.
  const isEdited = !!update.edited_message;
  if (isEdited) {
    return;
  }

  // FIX R2: determine admin status early to skip IP rate limit for admin.
  const adminMessage = isAdmin(env, msg.from.id);

  // Apply IP rate limit ONLY to non-admin paths.
  if (!adminMessage && clientIp !== 'unknown') {
    if (!(await store.checkIpRate(clientIp, 200, 3600))) {
      console.warn('IP rate limit exceeded', clientIp);
      return;
    }
  }

  if (msg.chat.type === 'group' || msg.chat.type === 'supergroup') {
    if (await handleGroupAiMessage(msg, env, store, tg)) return;
    return;
  }

  if (msg.chat.type !== 'private') return;

  if (adminMessage) {
    try {
      await handleAdminMessage(msg, env, store, tg);
    } catch (e) {
      await tg.sendMessage(env.ADMIN_UID, `⚠️ 处理出错：${(e as Error).message}`).catch(() => {});
    }
    return;
  }

  await handleUserMessage(msg, env, store, tg);
}

async function handleUserMessage(msg: TgMessage, env: Env, store: Store, tg: Telegram): Promise<void> {
  const userId = msg.from!.id;
  const text = msg.text ?? msg.caption ?? '';

  if (await store.isBlocked(userId)) {
    await handleBlockedUserMessage(userId, text, env, store, tg);
    return;
  }

  // FIX Q11: rate limit FIRST, before /start and verify paths. Without this,
  // an attacker could spam /start to reset the verify state and never hit the
  // 5-tries-per-challenge cap, defeating brute-force protection entirely.
  // The rate limit is 5 messages per minute per user, which is enough for
  // legitimate verification flow (one /start + one answer = 2 messages).
  // SECURITY FIX (H1): atomic-ish rate limit via KV list tokens
  // SECURITY FIX (H8): silent drop on rate limit (no message back)
  // FIX R1: use scope='msg' to avoid prefix collision with 'ban' and 'start' scopes.
  if (!(await store.hitRate(userId, 5, 60, 'msg'))) {
    // Silently drop. Sending a "too fast" message reveals rate-limit timing.
    return;
  }

  let profile = await store.getUser(userId);
  if (!profile) {
    const fn = msg.from!.first_name;
    const ln = msg.from!.last_name;
    const name = [fn, ln].filter(Boolean).join(' ') || msg.from!.username || String(userId);
    profile = {
      id: userId,
      name,
      username: msg.from!.username,
      verified: false,
      greeted: false,
      createdAt: Date.now(),
      lastSeenAt: Date.now(),
    };
    await store.saveUser(profile);
  }

  // FIX B1: /start handling — reset verification, send welcome, issue challenge,
  // and STOP. The original code fell through to ensureVerified which issued a
  // SECOND challenge (because /start inside ensureVerified clears verify state
  // and calls issueChallenge again), so the user got two messages and the
  // first challenge's answer was impossible to match. Now /start is terminal.
  // FIX Q16: don't double-saveUser — resetVerification already updates profile,
  // so we only need to saveUser once with the greeted reset.
  // FIX Q18: cap /start frequency to 3 per hour per user. Without this, an
  // attacker could spam /start (5/min via hitRate = 7200/day) to drain KV
  // write budget (each /start = 1 setVerifyAnswer + 1 saveUser = 2 writes).
  // 3/hour is plenty for legitimate use (user re-opens chat, clicks start).
  // FIX R1: use scope='start' to isolate from 'msg' and 'ban' scopes.
  if (text.trim() === '/start') {
    if (!(await store.hitRate(userId, 3, 3600, 'start'))) {
      // /start rate limit exceeded — silent drop. The per-message hitRate(5/min)
      // already passed, but we have a separate /start budget to protect KV writes.
      return;
    }
    await tg.sendMessage(userId, env.WELCOME_MESSAGE || '你好。').catch(() => {});
    // resetVerification sets verified=false, greeted=false, saves profile,
    // and clears verify state. No need for a separate saveUser.
    await store.resetVerification(userId);
    // Refresh local profile to reflect the reset
    profile.verified = false;
    profile.greeted = false;
    // Issue a fresh challenge via ensureVerified with empty text (not '/start')
    // so it doesn't recurse. We pass an empty string to skip the /start branch.
    await ensureVerified(profile, '', env, store, tg);
    return;
  }

  if (!profile.verified) {
    const ok = await ensureVerified(profile, text, env, store, tg);
    if (!ok) return;
  }

  // FIX H4-revised (v0.5): per user request, ALL message types are now accepted
  // for forwarding to admin. The AI filter runs on whatever text we can extract
  // (caption, sticker emoji, contact name, etc.). Messages with no extractable
  // text skip AI filtering and are forwarded directly (the admin can judge
  // visually).
  //
  // Extract text for AI filtering based on message type:
  //   - text / caption: use directly
  //   - sticker: use emoji (e.g. "😀")
  //   - contact: use first_name + phone_number
  //   - location: "(位置信息)" — no text to filter
  //   - other media with caption: caption
  //   - other media without caption: skip AI filter (forward directly)
  const hasMedia = !!(
    msg.photo?.length ||
    msg.document ||
    msg.video ||
    msg.voice ||
    msg.audio ||
    msg.sticker ||
    msg.animation ||
    msg.video_note ||
    msg.contact ||
    msg.location ||
    msg.dice
  );
  let filterText = '';
  let mediaTypeLabel = '';
  if (msg.text) {
    filterText = msg.text;
  } else if (msg.caption) {
    filterText = msg.caption;
    mediaTypeLabel = '[媒体附件] ';
  } else if (msg.sticker?.emoji) {
    filterText = `[贴纸] ${msg.sticker.emoji}`;
    mediaTypeLabel = '[贴纸] ';
  } else if (msg.contact) {
    filterText = `[联系人] ${msg.contact.first_name ?? ''} ${msg.contact.last_name ?? ''} ${msg.contact.phone_number ?? ''}`.trim();
    mediaTypeLabel = '[联系人] ';
  } else if (msg.location) {
    filterText = `[位置] 经度${msg.location.longitude.toFixed(4)} 纬度${msg.location.latitude.toFixed(4)}`;
    mediaTypeLabel = '[位置] ';
  } else if (msg.dice) {
    // Dice / slot machine / bowling emoji — Telegram built-in games.
    // No spam potential, forward directly.
    filterText = `[骰子] ${msg.dice.emoji}=${msg.dice.value}`;
    mediaTypeLabel = '[骰子] ';
  } else if (hasMedia) {
    // Media without caption and without extractable text — skip AI filter,
    // forward directly. Admin will see the media and judge visually.
    filterText = '';
    mediaTypeLabel = '[媒体] ';
  }

  // FIX B6: short-circuit when filter is disabled OR no text to filter on.
  // FIX H4-revised: if filterText is empty (e.g. photo without caption),
  // skip AI filter entirely and forward directly.
  // NOTE: rate limit already enforced at the top of handleUserMessage (Q11 fix).
  if (filterText && (env.FILTER_ENABLED ?? 'true') === 'true') {
    const activeModel = (await store.getActiveModel()) || env.AI_MODEL;
    const textForFilter = mediaTypeLabel ? `${mediaTypeLabel}${filterText}` : filterText;
    const c = await classifyMessage(textForFilter, env, activeModel);
    if (shouldIntercept(c, env, filterText)) {
      const violationCount = await store.incrementViolation(userId);
      const id = `${userId}-${msg.message_id}`;
      // SECURITY FIX (M3): redact PII before storing
      const redactedText = sanitizeForLog(filterText, 1000);
      await store.saveIntercepted({
        id,
        userId,
        text: redactedText,
        category: c.category,
        confidence: c.confidence,
        reason: c.reason,
        provider: c.provider,
        time: Date.now(),
        violationCount,
      });
      const threshold = Number(env.AUTO_BAN_THRESHOLD || '3');
      if (threshold > 0 && violationCount >= threshold) {
        await store.block(userId, `auto ban after ${violationCount} intercepted messages`, 'auto');
        // FIX B20: retry critical admin notification once
        await tg.sendMessage(userId, env.BAN_MESSAGE || '你已被系统封禁。如需申诉，请发送 /appeal <申诉说明>。').catch(() => {});
        await sendToAdminWithRetry(tg, env.ADMIN_UID,
          `🚫 自动封禁 uid:${userId}\n违规次数：${violationCount}\n类别：${c.category}\n详情：/intercepts`
        );
        await store.logAdminAction(0, 'auto_ban', `uid:${userId}`, `violation #${violationCount}, category=${c.category}`);
      } else {
        await tg.sendMessage(userId, '您的消息已收到。').catch(() => {});
      }
      return;
    }
    // FIX B5: append real user text (not caption) to context, so ghostwriter
    // has accurate history. For media messages, include a media marker.
    const ctxContent = mediaTypeLabel ? `${mediaTypeLabel}${filterText}` : filterText;
    await store.appendContext(String(userId), { role: 'user', content: ctxContent }, Number(env.AI_CONTEXT_ROUNDS || '6'));
  }

  if (env.AUTO_GREETING && !profile.greeted) {
    await tg.sendMessage(userId, env.AUTO_GREETING).catch(() => {});
    profile.greeted = true;
    await store.saveUser(profile);
  }

  const relay = makeRelay(env, store, tg);
  await relay.deliverToAdmin(msg);
}

// FIX B20: retry critical admin notifications once on transient failure.
async function sendToAdminWithRetry(tg: Telegram, adminId: string, text: string): Promise<void> {
  try {
    await tg.sendMessage(adminId, text);
  } catch (e) {
    console.warn('admin notify first attempt failed, retrying:', (e as Error).message);
    try {
      await tg.sendMessage(adminId, text);
    } catch (e2) {
      console.error('admin notify retry failed:', (e2 as Error).message);
    }
  }
}

async function handleBlockedUserMessage(
  userId: number,
  text: string,
  env: Env,
  store: Store,
  tg: Telegram,
): Promise<void> {
  // FIX Q17: rate limit blocked users too. Without this, a banned user could
  // spam /appeal or any message to drain KV writes (incrementAppeal per msg)
  // and Telegram API quota. 2 messages per minute is enough for legitimate
  // appeal submission.
  // FIX R1: use scope='ban' to avoid prefix collision with 'msg' scope.
  // Previously a banned user's hitRate(2,60) and a normal user's hitRate(5,60)
  // shared the same prefix, causing interference after ban/unban transitions.
  if (!(await store.hitRate(userId, 2, 60, 'ban'))) {
    return; // silent drop
  }

  if (text.trim().startsWith('/appeal')) {
    const appealText = text.replace(/^\/appeal\s*/, '').trim();
    const maxAttempts = Number(env.APPEAL_MAX_ATTEMPTS || '2');
    const attempts = await store.incrementAppeal(userId);
    if (attempts > maxAttempts) {
      await tg.sendMessage(userId, '申诉次数已用完，请等待管理员处理。').catch(() => {});
      return;
    }
    await tg.sendMessage(userId, env.APPEAL_MESSAGE || '申诉已收到，管理员会视情况处理。').catch(() => {});
    // SECURITY FIX (M3): redact PII in appeal notification
    const safeAppeal = sanitizeForLog(appealText || '(未填写说明)', 500);
    await tg
      .sendMessage(
        env.ADMIN_UID,
        `📩 封禁申诉 uid:${userId}\n次数：${attempts}/${maxAttempts}\n内容：${safeAppeal}\n\n处理：/unban ${userId}`,
      )
      .catch(() => {});
    return;
  }

  await tg.sendMessage(userId, env.BAN_MESSAGE || '你已被系统封禁。如需申诉，请发送 /appeal <申诉说明>。').catch(() => {});
}
