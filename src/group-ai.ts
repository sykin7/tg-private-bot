import type { Env, TgMessage } from './types';
import { Store } from './store';
import { Telegram, displayName } from './telegram';
import { chatComplete } from './ai-filter';
import { formatTelegramHtml } from './format';
import { appendSources, decideSearchQuick, renderSearchContext, runSearch, searchSystemPrompt, withSearchContext, type SearchResult } from './search';
import { truncateForAI } from './sanitize';

const GROUP_PROMPT =
  '你是一个 Telegram 群聊里的 AI 助手。只回答被明确 @ 提到的问题。' +
  '回答要自然、简洁、有帮助，适合群聊阅读；不要假装是群管理员，不要处理封禁/管理命令。' +
  '如果问题需要最新信息且提供了搜索结果，请基于搜索结果回答并附来源；不要编造。';

function isGroupChat(msg: TgMessage): boolean {
  return msg.chat.type === 'group' || msg.chat.type === 'supergroup';
}

function stripLeadingAt(username: string): string {
  return username.trim().replace(/^@/, '');
}

async function getBotUsername(env: Env, store: Store, tg: Telegram): Promise<string | null> {
  const configured = stripLeadingAt(env.BOT_USERNAME || '');
  if (configured) return configured.toLowerCase();

  const cached = await store.getBotUsername();
  if (cached) return stripLeadingAt(cached).toLowerCase();

  // FIX F3: getMe may succeed but setBotUsername (KV write) may fail (budget
  // exhausted). Previously we caught this and returned null, disabling group
  // AI entirely even though we had the username in hand. Now we return the
  // username regardless of cache write success — next request will retry
  // the cache write (or hit cache if it eventually succeeds).
  let meUsername: string | null = null;
  try {
    const me = await tg.getMe();
    meUsername = me.username ?? null;
  } catch (e) {
    console.error('getMe failed in group-ai', (e as Error).message);
    return null;
  }
  if (!meUsername) return null;
  // Best-effort cache write — failure here is acceptable (just means next
  // request will call getMe again).
  await store.setBotUsername(meUsername).catch((e) => {
    console.warn('setBotUsername cache write failed (non-fatal)', (e as Error).message);
  });
  return stripLeadingAt(meUsername).toLowerCase();
}

function extractMentionQuestion(msg: TgMessage, botUsername: string): string | null {
  const text = msg.text ?? msg.caption ?? '';
  if (!text) return null;

  const mention = `@${botUsername.toLowerCase()}`;
  const lower = text.toLowerCase();
  if (!lower.includes(mention)) return null;

  return text.replace(new RegExp(`@${escapeRegExp(botUsername)}`, 'gi'), '').trim();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function clampText(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars)}\n\n（内容较长，已截断）`;
}

async function sendGroupAiText(tg: Telegram, chatId: number, replyToMessageId: number, text: string, maxChars: number): Promise<void> {
  const clipped = clampText(text, maxChars);
  const html = formatTelegramHtml(clipped);
  const extra = {
    parse_mode: 'HTML',
    reply_parameters: { message_id: replyToMessageId },
  };

  if (html.length <= 3900) {
    await tg.sendMessage(chatId, html, extra);
    return;
  }
  await tg.sendLong(chatId, clipped, { reply_parameters: { message_id: replyToMessageId }, parse_mode: 'HTML' });
}

export async function handleGroupAiMessage(
  msg: TgMessage,
  env: Env,
  store: Store,
  tg: Telegram,
): Promise<boolean> {
  if (!isGroupChat(msg)) return false;
  if ((env.GROUP_AI_ENABLED ?? 'false') !== 'true') return false;

  const text = msg.text ?? msg.caption ?? '';
  if (!text.includes('@')) return false;

  const botUsername = await getBotUsername(env, store, tg);
  if (!botUsername) return false;

  const question = extractMentionQuestion(msg, botUsername);
  if (question === null) return false;

  if (!question) {
    await tg.sendMessage(msg.chat.id, `请在 @${botUsername} 后面写上问题喵～`, {
      reply_parameters: { message_id: msg.message_id },
    });
    return true;
  }

  const userId = msg.from?.id;
  if (!userId) return true;

  // SECURITY FIX (M7): blocked users cannot trigger group AI
  if (await store.isBlocked(userId)) {
    // Silently ignore — do not reveal that user is blocked
    return true;
  }

  const cooldownSeconds = Number(env.GROUP_USER_COOLDOWN_SECONDS || '30');
  if (!(await store.hitGroupUserCooldown(msg.chat.id, userId, cooldownSeconds))) {
    await tg.sendMessage(msg.chat.id, '你问得有点快啦，稍等一下再 @ 我～', {
      reply_parameters: { message_id: msg.message_id },
    });
    return true;
  }

  const maxConcurrency = Math.max(1, Number(env.GROUP_AI_MAX_CONCURRENCY || '1'));
  // FIX B19: respect GROUP_AI_LOCK_TTL_SECONDS config if set, otherwise
  // derive from AI_TIMEOUT_MS + 10s safety margin.
  // FIX v0.5: AI_TIMEOUT_MS default is now 25s (CF free-tier 30s cap), so
  // derived lock TTL is 35s. Configured default in wrangler.jsonc is 120s
  // for safety margin; users can lower it if they want stricter timeouts.
  const configuredLockTtl = Number(env.GROUP_AI_LOCK_TTL_SECONDS || '0');
  const lockTtl = configuredLockTtl > 0
    ? configuredLockTtl
    : Math.max(15, Math.ceil(Number(env.AI_TIMEOUT_MS || '25000') / 1000) + 10);
  const lockResult = await store.tryAcquireGroupLock(msg.chat.id, maxConcurrency, lockTtl);
  if (!lockResult.acquired) {
    await tg.sendMessage(msg.chat.id, '我正在回答上一条问题，稍后再喊我一下～', {
      reply_parameters: { message_id: msg.message_id },
    });
    return true;
  }
  const lockToken = lockResult.token;

  const maxInputChars = Math.max(100, Number(env.GROUP_AI_MAX_INPUT_CHARS || '1200'));
  const maxOutputChars = Math.max(300, Number(env.GROUP_AI_MAX_OUTPUT_CHARS || '1800'));
  const rounds = Math.max(1, Number(env.GROUP_AI_CONTEXT_ROUNDS || '4'));
  // SECURITY FIX (H5): per-user context to prevent cross-user prompt injection
  const contextKey = `group:${msg.chat.id}:user:${userId}`;
  const userName = displayName(msg.from);
  const prompt = `${userName}: ${clampText(question, maxInputChars)}`;

  // FIX E13: ack sendMessage must be inside try block so that if it fails,
  // the finally clause still releases the lock. Previously ack was outside
  // try, so a Telegram API failure here would leave the lock held until TTL
  // expiry (35-120s), blocking all subsequent group AI requests.
  let ack: { message_id: number };
  try {
    ack = await tg.sendMessage(msg.chat.id, '🤔 我想想喵…', {
      reply_parameters: { message_id: msg.message_id },
    });
  } catch (e) {
    // ack failed — release lock immediately and bail.
    console.warn('group-ai: ack sendMessage failed, releasing lock', (e as Error).message);
    await store.releaseGroupLock(msg.chat.id, lockToken).catch(() => {});
    return true;
  }

  try {
    const history = await store.getContext(contextKey);
    history.push({ role: 'user', content: prompt });
    const model = (await store.getActiveModel()) || env.AI_MODEL;
    // FIX P36/P37: use decideSearchQuick (8s cap) to stay within CF free-tier
    // 30s ctx.waitUntil budget. Returns false on any failure.
    let answer: string;
    const needSearch = await decideSearchQuick(question, env, model);
    if (needSearch) {
      await tg.editMessageText(msg.chat.id, ack.message_id, '🔎 我查一下再回答…').catch(() => {});
      let results: SearchResult[] = [];
      try {
        results = await runSearch(question.slice(0, 200), env);
      } catch (searchErr) {
        console.warn('group-ai search failed, degrading:', (searchErr as Error).message);
      }
      if (results.length) {
        const searchContext = renderSearchContext(question.slice(0, 200), results);
        const searched = await chatComplete(withSearchContext(history, searchContext), env, searchSystemPrompt(GROUP_PROMPT), model);
        answer = appendSources(searched, results);
      } else {
        // Search returned nothing or failed — answer without search context.
        answer = await chatComplete(history, env, GROUP_PROMPT, model);
      }
    } else {
      answer = await chatComplete(history, env, GROUP_PROMPT, model);
    }

    const finalText = answer && answer.trim() ? answer : 'AI 暂时没有生成内容，请稍后再试。';
    await sendGroupAiText(tg, msg.chat.id, msg.message_id, finalText, maxOutputChars);
    await tg.editMessageText(msg.chat.id, ack.message_id, '✅ 已回答').catch(() => {});
    await store.appendContext(contextKey, { role: 'user', content: truncateForAI(prompt, 1000) }, rounds);
    await store.appendContext(contextKey, { role: 'assistant', content: truncateForAI(finalText, 2000) }, rounds);
  } catch (e) {
    // SECURITY FIX (M8): don't pollute context with error message
    await tg
      .editMessageText(msg.chat.id, ack.message_id, `⚠️ 群聊 AI 出错：${(e as Error).message}`)
      .catch(async () => {
        await tg.sendMessage(msg.chat.id, `⚠️ 群聊 AI 出错：${(e as Error).message}`).catch(() => {});
      });
  } finally {
    // FIX B2: release the specific token we acquired, not the oldest.
    await store.releaseGroupLock(msg.chat.id, lockToken).catch(() => {});
  }

  return true;
}
