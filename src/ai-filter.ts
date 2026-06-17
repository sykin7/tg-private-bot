import type { Env, Classification, SpamCategory, ChatTurn } from './types';
import { keywordHit } from './moderation';
import { truncateForAI } from './sanitize';

const SYSTEM_PROMPT =
  '你是一个 Telegram 私聊门卫，只拦截明确的广告、诈骗和垃圾骚扰。判断用户发来的一条消息属于哪一类，并只返回一个 JSON 对象，不要任何额外文字。' +
  '类别取值：normal(正常)、ad(明确广告营销)、scam(诈骗)、spam(垃圾骚扰)。' +
  '重要规则：正常商务沟通、项目合作、咨询报价、询问是否可以聊广告、提到"可能涉及广告/推广/合作"的礼貌开场，都应判为 normal，confidence 不超过 0.4。' +
  '只有出现明确批量投放、引流链接、刷量、博彩色情、贷款返利、虚假中奖、钱包助记词、钓鱼链接、重复骚扰、强推产品服务等明显意图时，才判为 ad/scam/spam。' +
  '不确定时一律判 normal。输出格式：{"category":"normal|ad|scam|spam","confidence":0~1,"reason":"简短中文理由"}' +
  // SECURITY FIX (H9): instruct AI not to echo PII in reason
  '隐私保护：不要在 reason 字段中复述用户的手机号、邮箱、身份证号等个人信息。';

function parseClassification(raw: string): Omit<Classification, 'provider'> | null {
  const match = raw.match(/\{[\s\S]*\}/);
  if (!match) return null;
  try {
    const obj = JSON.parse(match[0]) as { category?: string; confidence?: number; reason?: string };
    const cat = obj.category as SpamCategory;
    if (!['normal', 'ad', 'scam', 'spam'].includes(cat)) return null;
    return {
      category: cat,
      confidence: typeof obj.confidence === 'number' ? obj.confidence : 0.5,
      reason: obj.reason ?? '',
    };
  } catch {
    return null;
  }
}

async function classifyViaRelay(text: string, env: Env, model: string): Promise<Omit<Classification, 'provider'> | null> {
  if (!env.AI_BASE_URL || !env.AI_API_KEY) return null;
  // FIX B7: classification should be fast. Use a dedicated short timeout
  // (default 10s) so a slow relay doesn't block the user's message flow.
  // Separate from AI_TIMEOUT_MS which is for full chat completions.
  const classifyTimeoutMs = Number(env.AI_CLASSIFY_TIMEOUT_MS || '10000');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), classifyTimeoutMs);
  try {
    // SECURITY FIX (H9): truncate user text before sending to relay
    const safeText = truncateForAI(text, 1000);
    const res = await fetch(`${env.AI_BASE_URL.replace(/\/$/, '')}/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${env.AI_API_KEY}` },
      body: JSON.stringify({
        model,
        temperature: 0,
        messages: [
          { role: 'system', content: SYSTEM_PROMPT },
          { role: 'user', content: safeText },
        ],
      }),
      signal: controller.signal,
    });
    if (!res.ok) return null;
    const json = (await res.json()) as { choices?: { message?: { content?: string } }[] };
    const content = json.choices?.[0]?.message?.content ?? '';
    return parseClassification(content);
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

async function classifyViaWorkersAi(text: string, env: Env): Promise<Omit<Classification, 'provider'> | null> {
  try {
    const safeText = truncateForAI(text, 1000);
    const out = (await env.AI.run(env.CF_AI_MODEL, {
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: safeText },
      ],
    })) as { response?: string };
    return parseClassification(out.response ?? '');
  } catch {
    return null;
  }
}

// Multi-tier: relay -> workers ai -> keyword -> default allow.
export async function classifyMessage(text: string, env: Env, model = env.AI_MODEL): Promise<Classification> {
  const provider = env.AI_PROVIDER || 'auto';
  const fallbackCf = (env.AI_FALLBACK_TO_CF ?? 'true') === 'true';

  if (provider === 'relay' || provider === 'auto') {
    const r = await classifyViaRelay(text, env, model);
    if (r) return { ...r, provider: 'relay' };
  }
  if (provider === 'workers_ai' || (provider === 'auto' && fallbackCf) || (provider === 'relay' && fallbackCf)) {
    const r = await classifyViaWorkersAi(text, env);
    if (r) return { ...r, provider: 'workers_ai' };
  }
  // keyword fallback
  if (keywordHit(text, env)) {
    return { category: 'spam', confidence: 1, reason: '命中屏蔽关键词', provider: 'keyword' };
  }
  return { category: 'normal', confidence: 0, reason: '未过滤(AI 不可用)', provider: 'none' };
}

const BLOCK_CATEGORIES: SpamCategory[] = ['ad', 'scam', 'spam'];

function isLowRiskBusinessOpening(c: Classification): boolean {
  if (c.category !== 'ad') return false;
  const reason = c.reason.toLowerCase();
  return (
    reason.includes('项目') ||
    reason.includes('合作') ||
    reason.includes('商务') ||
    reason.includes('详谈') ||
    reason.includes('可能')
  );
}

function isBusinessOpeningText(text: string): boolean {
  const normalized = text.toLowerCase();
  const hasBusinessIntent = /项目|合作|详谈|商务|报价|需求|咨询/.test(normalized);
  const hasSoftAdMention = /可能.*(广告|推广)|涉及.*(广告|推广)|聊.*(广告|推广)/.test(normalized);
  const hasHardSpamSignal = /https?:\/\/|t\.me\/|返利|兼职|刷单|博彩|彩票|贷款|私服|引流|加群|二维码|钱包|助记词|空投|中奖/.test(normalized);
  return hasBusinessIntent && (hasSoftAdMention || normalized.length <= 80) && !hasHardSpamSignal;
}

export function shouldIntercept(c: Classification, env: Env, text = ''): boolean {
  if ((env.FILTER_ENABLED ?? 'true') !== 'true') return false;
  const threshold = Number(env.FILTER_THRESHOLD || '0.75');
  if (text && isBusinessOpeningText(text)) return false;
  if (isLowRiskBusinessOpening(c) && c.confidence < 0.85) return false;
  return BLOCK_CATEGORIES.includes(c.category) && c.confidence >= threshold;
}

// Generic chat completion for ghostwriter / assistant, reusing the multi-tier channel.
// FIX P31: CF Workers free tier caps ctx.waitUntil at ~30s wall-clock. Default
// AI_TIMEOUT_MS in wrangler.jsonc is 25s (was 80s) so a single AI call cannot
// blow the budget. For paid tier, users can override AI_TIMEOUT_MS up to 60s.
export async function chatComplete(
  messages: ChatTurn[],
  env: Env,
  systemPrompt: string,
  model = env.AI_MODEL,
  timeoutOverrideMs?: number,
): Promise<string> {
  // SECURITY FIX: truncate each user message to prevent oversized payloads
  const safeMessages = messages.map((m) => ({
    ...m,
    content: m.role === 'user' ? truncateForAI(m.content, 2000) : m.content,
  }));
  const full = [{ role: 'system' as const, content: systemPrompt }, ...safeMessages];
  const provider = env.AI_PROVIDER || 'auto';
  // FIX P36/P37: cap timeout at 25s to stay within CF Workers free-tier
  // ctx.waitUntil 30s limit. decideSearch + chatComplete chained calls must
  // complete within 30s total, so each call gets at most ~12s by default.
  const timeoutMs = Math.min(timeoutOverrideMs ?? Number(env.AI_TIMEOUT_MS || '25000'), 25000);

  if (provider === 'relay' || provider === 'auto') {
    if (env.AI_BASE_URL && env.AI_API_KEY) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const res = await fetch(`${env.AI_BASE_URL.replace(/\/$/, '')}/chat/completions`, {
          method: 'POST',
          headers: { 'content-type': 'application/json', authorization: `Bearer ${env.AI_API_KEY}` },
          body: JSON.stringify({ model, messages: full }),
          signal: controller.signal,
        });
        if (res.ok) {
          const json = (await res.json()) as { choices?: { message?: { content?: string } }[] };
          const content = json.choices?.[0]?.message?.content;
          if (content) return content;
        }
      } catch {
        /* fall through to CF */
      } finally {
        clearTimeout(timeout);
      }
    }
  }
  try {
    const out = (await env.AI.run(env.CF_AI_MODEL, { messages: full })) as { response?: string };
    if (out.response) return out.response;
  } catch {
    /* fall through */
  }
  throw new Error('AI 暂时不可用，请稍后再试。');
}

// FIX P36: dedicated short-timeout variant for search decision. Returns
// false on any failure (timeout, parse error, AI unavailable) so caller
// can fall back to a plain (no-search) answer without doubling AI latency.
// Implementation lives in search.ts (decideSearchQuick) to keep
// SEARCH_DECISION_PROMPT and parseDecision in one place.

// List available models from the OpenAI-compatible relay station (GET /models).
export async function listModels(env: Env): Promise<string[]> {
  if (!env.AI_BASE_URL || !env.AI_API_KEY) return [];
  // FIX P32: add timeout so a hung relay doesn't block /model list.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const res = await fetch(`${env.AI_BASE_URL.replace(/\/$/, '')}/models`, {
      headers: { authorization: `Bearer ${env.AI_API_KEY}` },
      signal: controller.signal,
    });
    if (!res.ok) return [];
    const json = (await res.json()) as { data?: { id?: string }[] };
    // SECURITY FIX (L6): cap to 50 models
    return (json.data ?? []).map((m) => m.id).filter((x): x is string => !!x).slice(0, 50);
  } catch {
    return [];
  } finally {
    clearTimeout(timeout);
  }
}
