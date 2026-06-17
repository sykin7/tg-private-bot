import type { Env, ChatTurn } from './types';
import { chatComplete } from './ai-filter';
import { truncateForAI } from './sanitize';

export interface SearchDecision {
  needSearch: boolean;
  query: string;
  reason: string;
}

export interface SearchResult {
  title: string;
  url: string;
  snippet: string;
}

const SEARCH_DECISION_PROMPT =
  '你是搜索决策器。判断用户的问题是否需要联网搜索才能更可靠回答。' +
  '需要搜索的情况：询问最新/当前/今天/实时/新闻/价格/版本/官网/链接/赛程/天气/股票/政策变化，或用户明确说搜索/查一下/联网。' +
  '不需要搜索的情况：闲聊、写作、翻译、解释稳定知识、总结已给内容、角色扮演。' +
  '只返回 JSON：{"need_search":true|false,"query":"用于搜索的短查询","reason":"简短理由"}。';

function parseDecision(raw: string, fallbackQuery: string): SearchDecision {
  const match = raw.match(/\{[\s\S]*\}/);
  if (!match) return { needSearch: false, query: fallbackQuery, reason: 'decision parse failed' };
  try {
    const obj = JSON.parse(match[0]) as { need_search?: boolean; query?: string; reason?: string };
    return {
      needSearch: obj.need_search === true,
      query: (obj.query || fallbackQuery).trim().slice(0, 200) || fallbackQuery,
      reason: obj.reason || '',
    };
  } catch {
    return { needSearch: false, query: fallbackQuery, reason: 'decision json failed' };
  }
}

// FIX P36: dedicated short-timeout variant for search decision. Returns
// false on any failure (timeout, parse error, AI unavailable) so caller
// can fall back to a plain (no-search) answer without doubling AI latency.
// Uses an 8s hard cap (independent of AI_TIMEOUT_MS) so search decision
// can never blow the CF Workers free-tier 30s ctx.waitUntil budget.
export async function decideSearchQuick(
  question: string,
  env: Env,
  model: string,
): Promise<boolean> {
  if ((env.AUTO_SEARCH_ENABLED ?? 'true') !== 'true' || !env.SEARCH_API_KEY) {
    return false;
  }
  const decisionModel = env.SEARCH_DECISION_MODEL || model;
  const safeQuestion = truncateForAI(question, 500);
  try {
    const raw = await chatComplete(
      [{ role: 'user', content: safeQuestion }],
      env,
      SEARCH_DECISION_PROMPT,
      decisionModel,
      8000, // 8s hard cap for search decision
    );
    const decision = parseDecision(raw, question.slice(0, 200));
    return decision.needSearch;
  } catch {
    return false;
  }
}

// Legacy decideSearch — kept for backward compat but now thin wrapper.
// Prefer decideSearchQuick + runSearch directly.
export async function decideSearch(question: string, env: Env, model: string): Promise<SearchDecision> {
  if ((env.AUTO_SEARCH_ENABLED ?? 'true') !== 'true' || !env.SEARCH_API_KEY) {
    return { needSearch: false, query: question, reason: 'disabled' };
  }
  const decisionModel = env.SEARCH_DECISION_MODEL || model;
  const safeQuestion = truncateForAI(question, 500);
  try {
    const raw = await chatComplete(
      [{ role: 'user', content: safeQuestion }],
      env,
      SEARCH_DECISION_PROMPT,
      decisionModel,
      8000, // FIX P36: same 8s cap as decideSearchQuick
    );
    return parseDecision(raw, question.slice(0, 200));
  } catch (e) {
    // FIX P26/B26: on any failure, return needSearch=false so caller degrades.
    return { needSearch: false, query: question.slice(0, 200), reason: `decision failed: ${(e as Error).message}` };
  }
}

export async function runSearch(query: string, env: Env): Promise<SearchResult[]> {
  if (!env.SEARCH_API_KEY) return [];
  const provider = (env.SEARCH_PROVIDER || 'brave').toLowerCase();
  const maxResults = Math.max(1, Math.min(Number(env.SEARCH_MAX_RESULTS || '5'), 8));
  // SECURITY FIX: hard cap query length
  const safeQuery = query.slice(0, 200);
  if (provider === 'tavily') return searchTavily(safeQuery, env.SEARCH_API_KEY, maxResults);
  return searchBrave(safeQuery, env.SEARCH_API_KEY, maxResults);
}

// FIX P33: shared timeout helper for search API calls. CF Workers free tier
// caps ctx.waitUntil at ~30s, so 10s per search call leaves room for retry.
async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs = 10000): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

async function searchBrave(query: string, apiKey: string, maxResults: number): Promise<SearchResult[]> {
  const url = new URL('https://api.search.brave.com/res/v1/web/search');
  url.searchParams.set('q', query);
  url.searchParams.set('count', String(maxResults));
  let res: Response;
  try {
    res = await fetchWithTimeout(url.toString(), {
      headers: {
        accept: 'application/json',
        'x-subscription-token': apiKey,
      },
    });
  } catch (e) {
    throw new Error(`Brave Search network error: ${(e as Error).message}`);
  }
  if (!res.ok) throw new Error(`Brave Search failed: ${res.status}`);
  const json = (await res.json()) as {
    web?: { results?: { title?: string; url?: string; description?: string }[] };
  };
  return (json.web?.results ?? []).slice(0, maxResults).map((item) => ({
    title: (item.title || '(untitled)').slice(0, 200),
    url: (item.url || '').slice(0, 500),
    snippet: (item.description || '').slice(0, 500),
  }));
}

async function searchTavily(query: string, apiKey: string, maxResults: number): Promise<SearchResult[]> {
  let res: Response;
  try {
    res = await fetchWithTimeout('https://api.tavily.com/search', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey, query, max_results: maxResults, search_depth: 'basic' }),
    });
  } catch (e) {
    throw new Error(`Tavily Search network error: ${(e as Error).message}`);
  }
  if (!res.ok) throw new Error(`Tavily Search failed: ${res.status}`);
  const json = (await res.json()) as { results?: { title?: string; url?: string; content?: string }[] };
  return (json.results ?? []).slice(0, maxResults).map((item) => ({
    title: (item.title || '(untitled)').slice(0, 200),
    url: (item.url || '').slice(0, 500),
    snippet: (item.content || '').slice(0, 500),
  }));
}

export function renderSearchContext(query: string, results: SearchResult[]): string {
  if (!results.length) return `联网搜索查询：${query}\n没有搜索到可用结果。`;
  return [
    `联网搜索查询：${query}`,
    '请基于以下搜索结果回答，并在关键结论后标注来源编号，如 [1]。',
    ...results.map((r, index) => `[${index + 1}] ${r.title}\n${r.url}\n${r.snippet}`),
  ].join('\n\n');
}

export function appendSources(answer: string, results: SearchResult[]): string {
  if (!results.length) return answer;
  const sources = results.map((r, index) => `[${index + 1}] ${r.title}\n${r.url}`).join('\n');
  return `${answer}\n\n来源：\n${sources}`;
}

export function searchSystemPrompt(basePrompt: string): string {
  return (
    basePrompt +
    '你会收到联网搜索结果。请只基于搜索结果和已有上下文回答，不要编造来源；如果搜索结果不足，请明确说明。'
  );
}

export function withSearchContext(history: ChatTurn[], searchContext: string): ChatTurn[] {
  return [...history, { role: 'user', content: searchContext }];
}
