import { describe, it, expect, beforeEach } from 'vitest';
import type { KVNamespace } from '@cloudflare/workers-types';

// In-memory KV mock for testing store logic.
// Note: this mock is SEQUENTIAL (no concurrency), so it cannot reproduce
// real KV race conditions. It only tests the logical behavior of Store methods.
class MockKV implements KVNamespace {
  private store = new Map<string, { value: string; expiresAt?: number }>();

  async get(key: string): Promise<string | null> {
    const entry = this.store.get(key);
    if (!entry) return null;
    if (entry.expiresAt && entry.expiresAt < Date.now()) {
      this.store.delete(key);
      return null;
    }
    return entry.value;
  }

  async put(key: string, value: string, options?: { expirationTtl?: number }): Promise<void> {
    const expiresAt = options?.expirationTtl ? Date.now() + options.expirationTtl * 1000 : undefined;
    this.store.set(key, { value, expiresAt });
  }

  async delete(key: string): Promise<void> {
    this.store.delete(key);
  }

  async list(options?: { prefix?: string; limit?: number }): Promise<{ keys: { name: string }[] }> {
    const prefix = options?.prefix ?? '';
    const limit = options?.limit ?? 1000;
    const keys: { name: string }[] = [];
    for (const key of this.store.keys()) {
      if (key.startsWith(prefix)) {
        const entry = this.store.get(key)!;
        if (entry.expiresAt && entry.expiresAt < Date.now()) {
          this.store.delete(key);
          continue;
        }
        keys.push({ name: key });
        if (keys.length >= limit) break;
      }
    }
    return { keys };
  }
}

import { Store } from '../src/store';

function makeStore(): { store: Store; kv: MockKV } {
  const kv = new MockKV();
  const store = new Store(kv as unknown as KVNamespace);
  return { store, kv };
}

describe('Store', () => {
  let env: { store: Store; kv: MockKV };

  beforeEach(() => {
    env = makeStore();
  });

  describe('hitRate scope isolation (R1 fix)', () => {
    it('different scopes do NOT share rate budget', async () => {
      const userId = 12345;
      // Exhaust 'msg' scope (5/minute)
      for (let i = 0; i < 5; i++) {
        expect(await env.store.hitRate(userId, 5, 60, 'msg')).toBe(true);
      }
      // 'msg' should now be exhausted
      expect(await env.store.hitRate(userId, 5, 60, 'msg')).toBe(false);
      // 'ban' scope should still have budget (separate prefix)
      expect(await env.store.hitRate(userId, 2, 60, 'ban')).toBe(true);
      expect(await env.store.hitRate(userId, 2, 60, 'ban')).toBe(true);
      // 'ban' now exhausted
      expect(await env.store.hitRate(userId, 2, 60, 'ban')).toBe(false);
      // 'start' scope still has budget
      expect(await env.store.hitRate(userId, 3, 3600, 'start')).toBe(true);
    });

    it('same scope shares budget across calls', async () => {
      const userId = 99999;
      expect(await env.store.hitRate(userId, 3, 60, 'msg')).toBe(true);
      expect(await env.store.hitRate(userId, 3, 60, 'msg')).toBe(true);
      expect(await env.store.hitRate(userId, 3, 60, 'msg')).toBe(true);
      expect(await env.store.hitRate(userId, 3, 60, 'msg')).toBe(false);
    });

    it('default scope is "msg"', async () => {
      const userId = 88888;
      // Use default scope
      expect(await env.store.hitRate(userId, 2, 60)).toBe(true);
      expect(await env.store.hitRate(userId, 2, 60)).toBe(true);
      expect(await env.store.hitRate(userId, 2, 60)).toBe(false);
      // Explicit 'msg' scope should also be exhausted (same prefix)
      expect(await env.store.hitRate(userId, 2, 60, 'msg')).toBe(false);
    });
  });

  describe('verify failure counter', () => {
    it('increments and reads', async () => {
      expect(await env.store.recordVerifyFailure(111)).toBe(1);
      expect(await env.store.recordVerifyFailure(111)).toBe(2);
      expect(await env.store.getVerifyFailureCount(111)).toBe(2);
    });

    it('clears counter', async () => {
      await env.store.recordVerifyFailure(222);
      await env.store.recordVerifyFailure(222);
      await env.store.clearVerifyFailures(222);
      expect(await env.store.getVerifyFailureCount(222)).toBe(0);
    });

    it('isVerifyFailureLimitExceeded triggers at 10', async () => {
      expect(env.store.isVerifyFailureLimitExceeded(9)).toBe(false);
      expect(env.store.isVerifyFailureLimitExceeded(10)).toBe(true);
      expect(env.store.isVerifyFailureLimitExceeded(100)).toBe(true);
    });
  });

  describe('violations (R3 fix — clearViolations loops until empty)', () => {
    it('increments and counts', async () => {
      expect(await env.store.incrementViolation(333)).toBe(1);
      expect(await env.store.incrementViolation(333)).toBe(2);
      expect(await env.store.incrementViolation(333)).toBe(3);
      expect(await env.store.getViolationCount(333)).toBe(3);
    });

    it('clearViolations empties all tokens', async () => {
      // Add many violations (more than the old limit:200)
      for (let i = 0; i < 250; i++) {
        await env.store.incrementViolation(444);
      }
      expect(await env.store.getViolationCount(444)).toBe(250);
      // clearViolations should loop until empty (R3 fix)
      await env.store.clearViolations(444);
      expect(await env.store.getViolationCount(444)).toBe(0);
    });

    it('clearViolations handles 0 tokens', async () => {
      await env.store.clearViolations(555); // should not throw
      expect(await env.store.getViolationCount(555)).toBe(0);
    });
  });

  describe('appeals (R3 fix — clearAppeals loops until empty)', () => {
    it('clearAppeals empties all tokens', async () => {
      for (let i = 0; i < 150; i++) {
        await env.store.incrementAppeal(666);
      }
      expect(await env.store.getAppealCount(666)).toBe(150);
      await env.store.clearAppeals(666);
      expect(await env.store.getAppealCount(666)).toBe(0);
    });
  });

  describe('block / unblock', () => {
    it('block sets isBlocked true', async () => {
      expect(await env.store.isBlocked(777)).toBe(false);
      await env.store.block(777, 'test reason', 'manual');
      expect(await env.store.isBlocked(777)).toBe(true);
      const info = await env.store.getBlockInfo(777);
      expect(info?.reason).toBe('test reason');
      expect(info?.source).toBe('manual');
    });

    it('unblock clears violations and appeals', async () => {
      await env.store.incrementViolation(888);
      await env.store.incrementAppeal(888);
      await env.store.block(888, 'test', 'auto');
      expect(await env.store.isBlocked(888)).toBe(true);
      expect(await env.store.getViolationCount(888)).toBe(1);
      await env.store.unblock(888);
      expect(await env.store.isBlocked(888)).toBe(false);
      expect(await env.store.getViolationCount(888)).toBe(0);
      expect(await env.store.getAppealCount(888)).toBe(0);
    });
  });

  describe('IP rate limit (R7 fix — single-key counter)', () => {
    it('counts requests per IP per window', async () => {
      const ip = '1.2.3.4';
      for (let i = 0; i < 5; i++) {
        expect(await env.store.checkIpRate(ip, 5, 3600)).toBe(true);
      }
      expect(await env.store.checkIpRate(ip, 5, 3600)).toBe(false);
    });

    it('different IPs are independent', async () => {
      for (let i = 0; i < 3; i++) {
        expect(await env.store.checkIpRate('1.1.1.1', 3, 3600)).toBe(true);
      }
      expect(await env.store.checkIpRate('1.1.1.1', 3, 3600)).toBe(false);
      // Different IP still has budget
      expect(await env.store.checkIpRate('2.2.2.2', 3, 3600)).toBe(true);
    });
  });

  describe('write budget', () => {
    it('checkWriteBudget returns true under limit', async () => {
      expect(await env.store.checkWriteBudget()).toBe(true);
    });

    it('incrementWriteBudget accumulates', async () => {
      await env.store.incrementWriteBudget(100);
      await env.store.incrementWriteBudget(200);
      // After 300 writes, still under 800 limit
      expect(await env.store.checkWriteBudget()).toBe(true);
    });

    it('checkWriteBudget returns false at limit', async () => {
      await env.store.incrementWriteBudget(800);
      expect(await env.store.checkWriteBudget()).toBe(false);
    });
  });

  describe('seenUpdate', () => {
    it('returns false on first call, true on second', async () => {
      expect(await env.store.seenUpdate(12345)).toBe(false);
      expect(await env.store.seenUpdate(12345)).toBe(true);
    });

    it('different update_ids are independent', async () => {
      expect(await env.store.seenUpdate(1)).toBe(false);
      expect(await env.store.seenUpdate(2)).toBe(false);
      expect(await env.store.seenUpdate(1)).toBe(true);
      expect(await env.store.seenUpdate(2)).toBe(true);
    });
  });

  describe('admin AI mode', () => {
    it('defaults to off', async () => {
      expect(await env.store.getAdminAiMode()).toBe(false);
    });
    it('setAdminAiMode(true) persists', async () => {
      await env.store.setAdminAiMode(true);
      expect(await env.store.getAdminAiMode()).toBe(true);
    });
    it('setAdminAiMode(false) clears', async () => {
      await env.store.setAdminAiMode(true);
      await env.store.setAdminAiMode(false);
      expect(await env.store.getAdminAiMode()).toBe(false);
    });
  });

  describe('active model', () => {
    it('defaults to null', async () => {
      expect(await env.store.getActiveModel()).toBe(null);
    });
    it('setActiveModel persists', async () => {
      await env.store.setActiveModel('gpt-4o');
      expect(await env.store.getActiveModel()).toBe('gpt-4o');
    });
    it('clearActiveModel removes', async () => {
      await env.store.setActiveModel('gpt-4o');
      await env.store.clearActiveModel();
      expect(await env.store.getActiveModel()).toBe(null);
    });
  });

  describe('audit log', () => {
    it('logs and retrieves entries', async () => {
      await env.store.logAdminAction(123, 'ban', 'uid:456', 'reason');
      const log = await env.store.getAuditLog(10);
      expect(log.length).toBe(1);
      expect(log[0].actor).toBe(123);
      expect(log[0].action).toBe('ban');
      expect(log[0].target).toBe('uid:456');
    });

    it('caps detail at 500 chars', async () => {
      const longDetail = 'x'.repeat(1000);
      await env.store.logAdminAction(123, 'test', '-', longDetail);
      const log = await env.store.getAuditLog(1);
      expect(log[0].detail.length).toBe(500);
    });

    it('returns most recent first', async () => {
      await env.store.logAdminAction(1, 'first', '-', '');
      await env.store.logAdminAction(2, 'second', '-', '');
      await env.store.logAdminAction(3, 'third', '-', '');
      const log = await env.store.getAuditLog(10);
      expect(log[0].action).toBe('third');
      expect(log[1].action).toBe('second');
      expect(log[2].action).toBe('first');
    });
  });

  describe('group lock (R1 fix — token-based release)', () => {
    it('acquires and releases', async () => {
      const result = await env.store.tryAcquireGroupLock(123, 1, 60);
      expect(result.acquired).toBe(true);
      expect(result.token).not.toBeNull();
      await env.store.releaseGroupLock(123, result.token);
      // After release, can acquire again
      const result2 = await env.store.tryAcquireGroupLock(123, 1, 60);
      expect(result2.acquired).toBe(true);
    });

    it('rejects when limit reached', async () => {
      const r1 = await env.store.tryAcquireGroupLock(456, 1, 60);
      expect(r1.acquired).toBe(true);
      const r2 = await env.store.tryAcquireGroupLock(456, 1, 60);
      expect(r2.acquired).toBe(false);
      expect(r2.token).toBeNull();
    });

    it('release with wrong token does NOT release (R1 fix)', async () => {
      const r1 = await env.store.tryAcquireGroupLock(789, 1, 60);
      expect(r1.acquired).toBe(true);
      // Try to release with a fake token — should not release the real one
      await env.store.releaseGroupLock(789, 'fake-token');
      const r2 = await env.store.tryAcquireGroupLock(789, 1, 60);
      expect(r2.acquired).toBe(false); // still locked
      // Now release with correct token
      await env.store.releaseGroupLock(789, r1.token);
      const r3 = await env.store.tryAcquireGroupLock(789, 1, 60);
      expect(r3.acquired).toBe(true);
    });
  });
});
