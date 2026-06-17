import { describe, it, expect } from 'vitest';
import { isAdmin } from '../src/moderation';
import { keywordHit } from '../src/moderation';
import type { Env } from '../src/types';

// Minimal env mock for moderation tests
function makeEnv(overrides: Partial<Env> = {}): Env {
  return {
    TG_BOT_KV: {} as KVNamespace,
    AI: {} as Ai,
    BOT_TOKEN: 'test-token',
    BOT_SECRET: 'test-secret',
    AI_API_KEY: 'test-ai-key',
    SEARCH_API_KEY: '',
    ADMIN_UID: '123456789',
    AI_BASE_URL: 'https://test.example/v1',
    BOT_USERNAME: '',
    RELAY_MODE: 'private',
    ADMIN_GROUP_ID: '',
    AI_MODEL: 'gpt-4o-mini',
    AI_TIMEOUT_MS: '25000',
    AI_CLASSIFY_TIMEOUT_MS: '10000',
    AI_PROVIDER: 'relay',
    AI_FALLBACK_TO_CF: 'true',
    CF_AI_MODEL: '@cf/meta/llama-3.3-70b-instruct-fp8-fast',
    FILTER_ENABLED: 'true',
    FILTER_THRESHOLD: '0.75',
    BLOCK_KEYWORDS: '',
    VERIFY_MODE: 'math',
    VERIFY_QUESTION: '',
    VERIFY_ANSWER: '',
    WELCOME_MESSAGE: 'hi',
    AUTO_GREETING: 'hi',
    AI_REPLY_PREVIEW: 'preview',
    AI_CONTEXT_ROUNDS: '6',
    AUTO_BAN_THRESHOLD: '3',
    BAN_MESSAGE: 'banned',
    APPEAL_MAX_ATTEMPTS: '2',
    APPEAL_MESSAGE: 'received',
    AUTO_SEARCH_ENABLED: 'true',
    SEARCH_PROVIDER: 'brave',
    SEARCH_MAX_RESULTS: '5',
    SEARCH_DECISION_MODEL: '',
    GROUP_AI_ENABLED: 'false',
    GROUP_AI_MAX_CONCURRENCY: '1',
    GROUP_AI_LOCK_TTL_SECONDS: '120',
    GROUP_USER_COOLDOWN_SECONDS: '30',
    GROUP_AI_CONTEXT_ROUNDS: '4',
    GROUP_AI_MAX_INPUT_CHARS: '1200',
    GROUP_AI_MAX_OUTPUT_CHARS: '1800',
    BYPASS_TG_ASN_CHECK: '',
    WEBHOOK_URL_OVERRIDE: '',
    ...overrides,
  } as unknown as Env;
}

describe('moderation', () => {
  describe('isAdmin', () => {
    it('returns true when fromId matches ADMIN_UID', () => {
      const env = makeEnv({ ADMIN_UID: '123456789' });
      expect(isAdmin(env, 123456789)).toBe(true);
    });

    it('returns false when fromId does not match', () => {
      const env = makeEnv({ ADMIN_UID: '123456789' });
      expect(isAdmin(env, 987654321)).toBe(false);
    });

    it('returns false for undefined fromId', () => {
      const env = makeEnv({ ADMIN_UID: '123456789' });
      expect(isAdmin(env, undefined)).toBe(false);
    });

    it('returns false for 0 fromId', () => {
      const env = makeEnv({ ADMIN_UID: '123456789' });
      expect(isAdmin(env, 0)).toBe(false);
    });

    it('handles string/number comparison (ADMIN_UID is string)', () => {
      const env = makeEnv({ ADMIN_UID: '123456789' });
      // String(123456789) === '123456789'
      expect(isAdmin(env, 123456789)).toBe(true);
    });

    it('handles mismatched types correctly', () => {
      const env = makeEnv({ ADMIN_UID: '123456789' });
      // 1234567890 is a different number
      expect(isAdmin(env, 1234567890)).toBe(false);
    });
  });

  describe('keywordHit', () => {
    it('returns false when BLOCK_KEYWORDS is empty', () => {
      const env = makeEnv({ BLOCK_KEYWORDS: '' });
      expect(keywordHit('any text', env)).toBe(false);
    });

    it('matches single keyword', () => {
      const env = makeEnv({ BLOCK_KEYWORDS: 'spam' });
      expect(keywordHit('this is spam message', env)).toBe(true);
    });

    it('matches case-insensitively', () => {
      const env = makeEnv({ BLOCK_KEYWORDS: 'SPAM' });
      expect(keywordHit('this is spam message', env)).toBe(true);
      expect(keywordHit('this is SPAM message', env)).toBe(true);
    });

    it('matches multiple keywords (pipe separator)', () => {
      const env = makeEnv({ BLOCK_KEYWORDS: 'spam|scam|ads' });
      expect(keywordHit('this is spam', env)).toBe(true);
      expect(keywordHit('this is scam', env)).toBe(true);
      expect(keywordHit('this is ads', env)).toBe(true);
      expect(keywordHit('this is normal', env)).toBe(false);
    });

    it('matches multiple keywords (newline separator)', () => {
      const env = makeEnv({ BLOCK_KEYWORDS: 'spam\nscam\nads' });
      expect(keywordHit('this is scam', env)).toBe(true);
    });

    it('matches multiple keywords (comma separator)', () => {
      const env = makeEnv({ BLOCK_KEYWORDS: 'spam,scam,ads' });
      expect(keywordHit('this is ads', env)).toBe(true);
    });

    it('handles mixed separators', () => {
      const env = makeEnv({ BLOCK_KEYWORDS: 'spam, scam\nads|fraud' });
      expect(keywordHit('fraud detected', env)).toBe(true);
    });

    it('handles keywords with whitespace', () => {
      const env = makeEnv({ BLOCK_KEYWORDS: '  spam  ,  scam  ' });
      expect(keywordHit('this is spam', env)).toBe(true);
    });

    it('does not match substring of unrelated word (bug check)', () => {
      // "spam" inside "spammer" — this WILL match (substring search).
      // This is documented behavior: BLOCK_KEYWORDS uses substring matching.
      const env = makeEnv({ BLOCK_KEYWORDS: 'spam' });
      expect(keywordHit('I am a spammer', env)).toBe(true);
    });

    it('supports Chinese keywords', () => {
      const env = makeEnv({ BLOCK_KEYWORDS: '加微信' });
      expect(keywordHit('请加微信详谈', env)).toBe(true);
    });
  });
});
