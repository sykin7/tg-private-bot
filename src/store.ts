import type { Env, UserProfile, ChatTurn, AuditLogEntry } from './types';

export interface GhostDraft {
  id: string;
  userId: number;
  intent: string;
  draft: string;
  createdAt: number;
}

export interface BlockInfo {
  userId: number;
  reason: string;
  source: 'manual' | 'auto';
  createdAt: number;
}

export interface InterceptedRecord {
  id: string;
  userId: number;
  text: string;          // already redacted via sanitizeForLog before storage
  category: string;
  confidence?: number;
  reason: string;
  provider: string;
  time: number;
  violationCount?: number;
}

// Thin KV wrapper. All KV key conventions live here.
export class Store {
  constructor(private kv: KVNamespace) {}

  private async getJSON<T>(key: string): Promise<T | null> {
    const raw = await this.kv.get(key);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as T;
    } catch {
      return null;
    }
  }

  private putJSON(key: string, value: unknown, ttlSeconds?: number): Promise<void> {
    return this.kv.put(key, JSON.stringify(value), ttlSeconds ? { expirationTtl: ttlSeconds } : undefined);
  }

  // ---- user profile ----
  getUser(userId: number): Promise<UserProfile | null> {
    return this.getJSON<UserProfile>(`user:${userId}`);
  }

  async saveUser(profile: UserProfile): Promise<void> {
    // SECURITY FIX (M11): update lastSeenAt on every save
    profile.lastSeenAt = Date.now();
    await this.putJSON(`user:${profile.id}`, profile);
  }

  // ---- verification temp state ----
  // SECURITY FIX (L1): store SHA-1 hash of answer instead of plaintext.
  async setVerifyAnswer(userId: number, answerHash: string, ttl = 600): Promise<void> {
    return this.putJSON(`verify:${userId}`, { answerHash, tries: 0 }, ttl);
  }

  getVerify(userId: number): Promise<{ answerHash: string; tries: number } | null> {
    return this.getJSON<{ answerHash: string; tries: number }>(`verify:${userId}`);
  }

  bumpVerifyTries(userId: number, current: { answerHash: string; tries: number }): Promise<void> {
    return this.putJSON(`verify:${userId}`, { ...current, tries: current.tries + 1 }, 600);
  }

  clearVerify(userId: number): Promise<void> {
    return this.kv.delete(`verify:${userId}`);
  }

  async resetVerification(userId: number): Promise<void> {
    const profile = await this.getUser(userId);
    if (profile) {
      profile.verified = false;
      // SECURITY FIX (M11): also reset greeted so banned->start flow doesn't skip greeting
      profile.greeted = false;
      await this.saveUser(profile);
    }
    await this.clearVerify(userId);
  }

  // ---- reply mapping: admin message id -> user id ----
  // SECURITY FIX (C4): ttl extended to 30 days (was 7)
  mapAdminMsg(adminMsgId: number, userId: number, ttl = 60 * 60 * 24 * 30): Promise<void> {
    return this.kv.put(`msgmap:${adminMsgId}`, String(userId), { expirationTtl: ttl });
  }

  async resolveAdminMsg(adminMsgId: number): Promise<number | null> {
    const v = await this.kv.get(`msgmap:${adminMsgId}`);
    return v ? Number(v) : null;
  }

  // ---- blocklist ----
  async block(userId: number, reason = 'blocked', source: 'manual' | 'auto' = 'manual'): Promise<void> {
    const info: BlockInfo = { userId, reason, source, createdAt: Date.now() };
    await this.putJSON(`block:${userId}`, info);
  }

  async unblock(userId: number): Promise<void> {
    await this.kv.delete(`block:${userId}`);
    await this.clearViolations(userId);
    await this.clearAppeals(userId);
  }

  async getBlockInfo(userId: number): Promise<BlockInfo | null> {
    const parsed = await this.getJSON<BlockInfo>(`block:${userId}`);
    if (parsed) return parsed;
    const raw = await this.kv.get(`block:${userId}`);
    return raw ? { userId, reason: raw, source: 'manual', createdAt: 0 } : null;
  }

  async isBlocked(userId: number): Promise<boolean> {
    return (await this.getBlockInfo(userId)) !== null;
  }

  // ---- violations / auto ban ----
  // SECURITY FIX (H1): use list-based pseudo-atomic increment to reduce
  // concurrency race window. Still eventually consistent on KV, but
  // concurrent writers can no longer all read "0" and all write "1".
  // FIX B10: use crypto.randomUUID instead of Math.random for token uniqueness.
  // FIX R3-TEST: list limit was 200, which capped the count at 200 even when
  // more tokens existed. This silently broke AUTO_BAN_THRESHOLD > 200.
  // Now we list with a high enough limit (1000) to cover any sane threshold.
  async incrementViolation(userId: number): Promise<number> {
    const prefix = `violations:${userId}:`;
    const token = crypto.randomUUID();
    const key = `${prefix}${token}`;
    await this.kv.put(key, '1', { expirationTtl: 60 * 60 * 24 * 30 });
    const list = await this.kv.list({ prefix, limit: 1000 });
    return list.keys.length;
  }

  async getViolationCount(userId: number): Promise<number> {
    const list = await this.kv.list({ prefix: `violations:${userId}:`, limit: 1000 });
    return list.keys.length;
  }

  async clearViolations(userId: number): Promise<void> {
    // FIX R3: loop until all tokens are deleted. Previously limit:200 meant
    // if a user had >200 violation tokens (rare but possible after multiple
    // /forgive cycles), residual tokens would survive and corrupt the next
    // incrementViolation count.
    const prefix = `violations:${userId}:`;
    let deleted = 0;
    while (true) {
      const list = await this.kv.list({ prefix, limit: 1000 });
      if (list.keys.length === 0) break;
      await Promise.all(list.keys.map((k) => this.kv.delete(k.name)));
      deleted += list.keys.length;
      if (list.keys.length < 1000) break; // no more pages
      // Safety cap to avoid infinite loop in pathological cases
      if (deleted > 10000) {
        console.warn('clearViolations: exceeded 10000 deletions, breaking');
        break;
      }
    }
  }

  // ---- appeal attempts ----
  async incrementAppeal(userId: number): Promise<number> {
    const prefix = `appeals:${userId}:`;
    const token = crypto.randomUUID();
    await this.kv.put(`${prefix}${token}`, '1', { expirationTtl: 60 * 60 * 24 * 30 });
    // FIX R3-TEST: was limit:100, now 1000 to avoid silent count cap.
    const list = await this.kv.list({ prefix, limit: 1000 });
    return list.keys.length;
  }

  async getAppealCount(userId: number): Promise<number> {
    const list = await this.kv.list({ prefix: `appeals:${userId}:`, limit: 1000 });
    return list.keys.length;
  }

  async clearAppeals(userId: number): Promise<void> {
    // FIX R3: same loop-until-empty pattern as clearViolations.
    const prefix = `appeals:${userId}:`;
    let deleted = 0;
    while (true) {
      const list = await this.kv.list({ prefix, limit: 1000 });
      if (list.keys.length === 0) break;
      await Promise.all(list.keys.map((k) => this.kv.delete(k.name)));
      deleted += list.keys.length;
      if (list.keys.length < 1000) break;
      if (deleted > 10000) {
        console.warn('clearAppeals: exceeded 10000 deletions, breaking');
        break;
      }
    }
  }

  // ---- rate limit (per minute window) ----
  // SECURITY FIX (H1 + H8): use list-based tokens for approximate atomicity.
  // Each request writes a unique token; we count existing tokens to decide.
  // Window is fixed per 60s bucket.
  // FIX B10: use crypto.randomUUID for token uniqueness.
  // FIX P27: KV free tier is 1000 writes/day. Aggressive users could exhaust
  // this in minutes. The 5/minute per-user cap limits each user to ~7200
  // writes/day worst case, but in practice admin bans them long before that.
  // For full protection, see README guidance on upgrading to Workers Paid.
  //
  // FIX R1: add `scope` parameter to prevent prefix collision between different
  // rate limit callers. Previously hitRate(5,60) in handleUserMessage and
  // hitRate(2,60) in handleBlockedUserMessage shared the same prefix
  // `rate:{userId}:{bucket}:`, causing them to interfere with each other.
  // Now each caller passes a unique scope (e.g. 'msg', 'ban', 'start').
  async hitRate(userId: number, limit: number, windowSec = 60, scope = 'msg'): Promise<boolean> {
    const now = Date.now();
    const bucket = Math.floor(now / 1000 / windowSec);
    const prefix = `rate:${scope}:${userId}:${bucket}:`;
    // Check current count
    const existing = await this.kv.list({ prefix, limit: limit + 1 });
    if (existing.keys.length >= limit) return false;
    // Write new token
    const token = `${now}-${crypto.randomUUID()}`;
    await this.kv.put(`${prefix}${token}`, '1', { expirationTtl: windowSec + 5 });
    return true;
  }

  // ---- global write budget (P27) ----
  // Tracks approximate daily KV write count across all users. When exceeded,
  // non-essential writes (like context logging) are skipped to preserve
  // budget for critical writes (verification, blocks, etc.).
  // NOTE: This is best-effort — KV list counts are eventually consistent.
  private static readonly GLOBAL_WRITE_BUDGET_KEY = 'cfg:daily_writes';
  private static readonly GLOBAL_WRITE_BUDGET_LIMIT = 800; // leave 200 margin

  async checkWriteBudget(): Promise<boolean> {
    const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
    const key = `${Store.GLOBAL_WRITE_BUDGET_KEY}:${today}`;
    const current = Number((await this.kv.get(key)) ?? '0');
    return current < Store.GLOBAL_WRITE_BUDGET_LIMIT;
  }

  async incrementWriteBudget(count = 1): Promise<void> {
    const today = new Date().toISOString().slice(0, 10);
    const key = `${Store.GLOBAL_WRITE_BUDGET_KEY}:${today}`;
    const current = Number((await this.kv.get(key)) ?? '0');
    // TTL until end of next day (max 48h) so the counter cleans up.
    await this.kv.put(key, String(current + count), { expirationTtl: 60 * 60 * 48 });
  }

  // ---- IP / ASN rate limiting (P-anti-brute) ----
  // Defense against multi-account brute force and high-concurrency attacks.
  // Each Telegram webhook carries CF-Connecting-IP and cf.asn. We track
  // per-IP request count and per-IP verify-failure count, blocking IPs
  // that exceed thresholds.
  // NOTE: Telegram webhooks come from a small set of Telegram IPs, so
  // per-IP limiting here would throttle Telegram itself. The real value
  // is per-userId limiting (already done via hitRate) + per-IP verify
  // failure tracking (different IPs = different attackers, but Telegram
  // uses few IPs, so this is mostly a backstop).

  // Track verify failures per user (cumulative, 24h window).
  // If a user accumulates > GLOBAL_VERIFY_FAIL_LIMIT failures in 24h,
  // they are auto-banned regardless of per-challenge attempt count.
  private static readonly GLOBAL_VERIFY_FAIL_PREFIX = 'vfail:';
  private static readonly GLOBAL_VERIFY_FAIL_LIMIT = 10;
  private static readonly GLOBAL_VERIFY_FAIL_TTL = 60 * 60 * 24; // 24h

  async recordVerifyFailure(userId: number): Promise<number> {
    const key = `${Store.GLOBAL_VERIFY_FAIL_PREFIX}${userId}`;
    const current = Number((await this.kv.get(key)) ?? '0');
    const next = current + 1;
    await this.kv.put(key, String(next), { expirationTtl: Store.GLOBAL_VERIFY_FAIL_TTL });
    return next;
  }

  async getVerifyFailureCount(userId: number): Promise<number> {
    return Number((await this.kv.get(`${Store.GLOBAL_VERIFY_FAIL_PREFIX}${userId}`)) ?? '0');
  }

  async clearVerifyFailures(userId: number): Promise<void> {
    await this.kv.delete(`${Store.GLOBAL_VERIFY_FAIL_PREFIX}${userId}`);
  }

  isVerifyFailureLimitExceeded(count: number): boolean {
    return count >= Store.GLOBAL_VERIFY_FAIL_LIMIT;
  }

  // Track per-IP request rate using single-key counter (FIX R7: was list-based
  // but KV free tier has 1000 list ops/day limit — list-based IP rate limiting
  // would exhaust the budget at 500 requests/day. Single-key read-modify-write
  // has a concurrency race (multiple requests read same count, all write +1,
  // losing some increments), but for IP rate limiting this is acceptable:
  // undercount by a few requests is harmless, and the real protection is
  // per-userId hitRate which is still list-based for accuracy).
  async checkIpRate(ip: string, limit = 200, windowSec = 3600): Promise<boolean> {
    const bucket = Math.floor(Date.now() / 1000 / windowSec);
    const key = `iprate:${ip}:${bucket}`;
    const current = Number((await this.kv.get(key)) ?? '0');
    if (current >= limit) return false;
    // Best-effort increment. Race condition: concurrent requests may all read
    // the same `current` and all write `current + 1`, undercounting. Acceptable
    // for IP-level backstop limiting.
    await this.kv.put(key, String(current + 1), { expirationTtl: windowSec + 5 });
    return true;
  }

  // ---- idempotency for update_id ----
  // NOTE (M6): KV is eventually consistent so duplicate processing is still
  // possible in rare multi-region races. For most personal bots this is
  // acceptable. Upgrade to Durable Objects if you need strict dedup.
  async seenUpdate(updateId: number): Promise<boolean> {
    const key = `upd:${updateId}`;
    if (await this.kv.get(key)) return true;
    await this.kv.put(key, '1', { expirationTtl: 600 });
    return false;
  }

  // ---- intercepted messages ----
  // SECURITY FIX (M3): text is already redacted by caller via sanitizeForLog
  async saveIntercepted(record: InterceptedRecord): Promise<void> {
    await this.putJSON(`intercepted:${record.id}`, record, 60 * 60 * 24 * 30);
    const index = await this.getInterceptedIndex(100);
    const next = [record, ...index.filter((item) => item.id !== record.id)].slice(0, 100);
    await this.putJSON('intercepted:index', next, 60 * 60 * 24 * 30);
  }

  async getInterceptedIndex(limit = 10): Promise<InterceptedRecord[]> {
    // SECURITY FIX (M4): hard cap at 50 to prevent bulk PII exfiltration
    const safeLimit = Math.min(limit, 50);
    const items = (await this.getJSON<InterceptedRecord[]>('intercepted:index')) ?? [];
    return items.slice(0, safeLimit);
  }

  // ---- admin AI chat mode ----
  async getAdminAiMode(): Promise<boolean> {
    return (await this.kv.get('cfg:admin_ai_mode')) === 'on';
  }

  setAdminAiMode(on: boolean): Promise<void> {
    return on ? this.kv.put('cfg:admin_ai_mode', 'on') : this.kv.delete('cfg:admin_ai_mode');
  }

  // ---- active AI model override ----
  getActiveModel(): Promise<string | null> {
    return this.kv.get('cfg:model');
  }

  setActiveModel(model: string): Promise<void> {
    return this.kv.put('cfg:model', model);
  }

  clearActiveModel(): Promise<void> {
    return this.kv.delete('cfg:model');
  }

  // ---- bot profile cache ----
  getBotUsername(): Promise<string | null> {
    return this.kv.get('cfg:bot_username');
  }

  setBotUsername(username: string): Promise<void> {
    return this.kv.put('cfg:bot_username', username, { expirationTtl: 60 * 60 * 24 });
  }

  // ---- ghostwrite drafts ----
  saveGhostDraft(draft: GhostDraft, ttl = 60 * 60): Promise<void> {
    return this.putJSON(`draft:${draft.id}`, draft, ttl);
  }

  getGhostDraft(id: string): Promise<GhostDraft | null> {
    return this.getJSON<GhostDraft>(`draft:${id}`);
  }

  deleteGhostDraft(id: string): Promise<void> {
    return this.kv.delete(`draft:${id}`);
  }

  // ---- conversation context ----
  async getContext(key: string): Promise<ChatTurn[]> {
    return (await this.getJSON<ChatTurn[]>(`ctx:${key}`)) ?? [];
  }

  // FIX P22/P27: appendContext respects the global write budget. When the
  // daily KV write budget is close to exhaustion (free-tier limit ~1000/day),
  // context writes are skipped to preserve budget for critical operations
  // (verification, blocks, ban notifications).
  async appendContext(key: string, turn: ChatTurn, maxRounds: number): Promise<void> {
    const withinBudget = await this.checkWriteBudget();
    if (!withinBudget) {
      // Skip context logging — user can still chat, just without history.
      console.warn('KV write budget exhausted, skipping context append');
      return;
    }
    const turns = await this.getContext(key);
    turns.push(turn);
    const maxItems = maxRounds * 2;
    const trimmed = turns.slice(-maxItems);
    await this.putJSON(`ctx:${key}`, trimmed, 60 * 60 * 24 * 7);
    await this.incrementWriteBudget();
  }

  // ---- group AI concurrency / cooldown ----
  // SECURITY FIX (H1): use list-based pseudo-atomic lock.
  // FIX B2: lock tokens carry the chatId+timestamp so releaseGroupLock
  // can find and delete the specific token held by the current request,
  // rather than blindly deleting the oldest. Caller stores the returned
  // token name and passes it back to releaseGroupLock.
  async tryAcquireGroupLock(
    chatId: number,
    limit: number,
    ttlSeconds: number,
  ): Promise<{ acquired: boolean; token: string | null }> {
    const prefix = `lock:group:${chatId}:`;
    const existing = await this.kv.list({ prefix, limit: limit + 1 });
    if (existing.keys.length >= limit) {
      return { acquired: false, token: null };
    }
    // FIX B10: use crypto.randomUUID for token uniqueness
    const token = `${Date.now()}-${crypto.randomUUID()}`;
    const key = `${prefix}${token}`;
    await this.kv.put(key, '1', { expirationTtl: ttlSeconds });
    return { acquired: true, token };
  }

  async releaseGroupLock(chatId: number, token: string | null): Promise<void> {
    if (!token) return;
    // Delete the specific token held by this request.
    const key = `lock:group:${chatId}:${token}`;
    await this.kv.delete(key);
  }

  async hitGroupUserCooldown(chatId: number, userId: number, seconds: number): Promise<boolean> {
    if (seconds <= 0) return true;
    const key = `cooldown:group:${chatId}:${userId}`;
    if (await this.kv.get(key)) return false;
    await this.kv.put(key, '1', { expirationTtl: seconds });
    return true;
  }

  // ---- audit log (SECURITY FIX M1) ----
  async logAdminAction(actor: number, action: string, target: string, detail: string): Promise<void> {
    const entry: AuditLogEntry = {
      time: Date.now(),
      actor,
      action,
      target,
      detail: detail.slice(0, 500),
    };
    const log = (await this.getJSON<AuditLogEntry[]>('audit:log')) ?? [];
    log.unshift(entry);
    await this.putJSON('audit:log', log.slice(0, 1000), 60 * 60 * 24 * 90); // 90 days
  }

  async getAuditLog(limit = 20): Promise<AuditLogEntry[]> {
    const safeLimit = Math.min(limit, 100);
    const log = (await this.getJSON<AuditLogEntry[]>('audit:log')) ?? [];
    return log.slice(0, safeLimit);
  }
}

export function makeStore(env: Env): Store {
  return new Store(env.TG_BOT_KV);
}
