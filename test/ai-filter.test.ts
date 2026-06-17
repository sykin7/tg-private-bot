import { describe, it, expect } from 'vitest';
import { shouldIntercept } from '../src/ai-filter';
import type { Env, Classification } from '../src/types';

function makeEnv(overrides: Partial<Env> = {}): Env {
  return {
    TG_BOT_KV: {} as KVNamespace,
    AI: {} as Ai,
    BOT_TOKEN: '',
    BOT_SECRET: '',
    AI_API_KEY: '',
    SEARCH_API_KEY: '',
    ADMIN_UID: '1',
    AI_BASE_URL: '',
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
    WELCOME_MESSAGE: '',
    AUTO_GREETING: '',
    AI_REPLY_PREVIEW: 'preview',
    AI_CONTEXT_ROUNDS: '6',
    AUTO_BAN_THRESHOLD: '3',
    BAN_MESSAGE: '',
    APPEAL_MAX_ATTEMPTS: '2',
    APPEAL_MESSAGE: '',
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

function makeClassification(overrides: Partial<Classification> = {}): Classification {
  return {
    category: 'normal',
    confidence: 0.5,
    reason: '',
    provider: 'relay',
    ...overrides,
  };
}

describe('ai-filter shouldIntercept', () => {
  it('returns false when FILTER_ENABLED is false', () => {
    const env = makeEnv({ FILTER_ENABLED: 'false' });
    const c = makeClassification({ category: 'spam', confidence: 1.0 });
    expect(shouldIntercept(c, env, 'spam text')).toBe(false);
  });

  it('returns false for normal category regardless of confidence', () => {
    const env = makeEnv();
    const c = makeClassification({ category: 'normal', confidence: 0.99 });
    expect(shouldIntercept(c, env, 'any text')).toBe(false);
  });

  it('returns false for ad with confidence below threshold', () => {
    const env = makeEnv({ FILTER_THRESHOLD: '0.75' });
    const c = makeClassification({ category: 'ad', confidence: 0.74 });
    expect(shouldIntercept(c, env, 'ad text')).toBe(false);
  });

  it('returns true for ad with confidence at threshold', () => {
    const env = makeEnv({ FILTER_THRESHOLD: '0.75' });
    const c = makeClassification({ category: 'ad', confidence: 0.75 });
    expect(shouldIntercept(c, env, 'ad text')).toBe(true);
  });

  it('returns true for ad with confidence above threshold', () => {
    const env = makeEnv({ FILTER_THRESHOLD: '0.75' });
    const c = makeClassification({ category: 'ad', confidence: 0.95 });
    expect(shouldIntercept(c, env, 'ad text')).toBe(true);
  });

  it('returns true for scam at threshold', () => {
    const env = makeEnv({ FILTER_THRESHOLD: '0.75' });
    const c = makeClassification({ category: 'scam', confidence: 0.75 });
    expect(shouldIntercept(c, env, 'scam text')).toBe(true);
  });

  it('returns true for spam at threshold', () => {
    const env = makeEnv({ FILTER_THRESHOLD: '0.75' });
    const c = makeClassification({ category: 'spam', confidence: 0.75 });
    expect(shouldIntercept(c, env, 'spam text')).toBe(true);
  });

  it('respects custom threshold', () => {
    const env = makeEnv({ FILTER_THRESHOLD: '0.9' });
    const c = makeClassification({ category: 'ad', confidence: 0.8 });
    expect(shouldIntercept(c, env, 'ad text')).toBe(false);
  });

  describe('business opening text bypass', () => {
    it('does NOT intercept short business opening text even if AI flags ad', () => {
      const env = makeEnv({ FILTER_THRESHOLD: '0.75' });
      const c = makeClassification({ category: 'ad', confidence: 0.95 });
      // Text contains business intent keywords and is short (≤80 chars)
      expect(shouldIntercept(c, env, '咨询合作')).toBe(false);
      expect(shouldIntercept(c, env, '项目合作')).toBe(false);
      expect(shouldIntercept(c, env, '商务报价')).toBe(false);
    });

    it('intercepts business opening text that contains hard spam signals', () => {
      const env = makeEnv({ FILTER_THRESHOLD: '0.75' });
      const c = makeClassification({ category: 'ad', confidence: 0.95 });
      // Has hard spam signal (t.me/) — should intercept
      expect(shouldIntercept(c, env, '项目合作 t.me/scammer')).toBe(true);
      expect(shouldIntercept(c, env, '商务报价 加群详谈')).toBe(true);
      expect(shouldIntercept(c, env, '咨询返利项目')).toBe(true);
    });

    it('intercepts long business text (>80 chars) without soft ad mention', () => {
      const env = makeEnv({ FILTER_THRESHOLD: '0.75' });
      const c = makeClassification({ category: 'ad', confidence: 0.95 });
      const longText = '项目合作'.repeat(30); // >80 chars, no soft ad mention
      expect(shouldIntercept(c, env, longText)).toBe(true);
    });

    it('does NOT intercept long business text WITH soft ad mention', () => {
      const env = makeEnv({ FILTER_THRESHOLD: '0.75' });
      const c = makeClassification({ category: 'ad', confidence: 0.95 });
      const longText = '项目合作 可能涉及广告 ' + 'x'.repeat(100);
      expect(shouldIntercept(c, env, longText)).toBe(false);
    });
  });

  describe('low-risk business opening (AI reason-based bypass)', () => {
    it('does NOT intercept low-confidence ad with business reason', () => {
      const env = makeEnv({ FILTER_THRESHOLD: '0.75' });
      const c = makeClassification({
        category: 'ad',
        confidence: 0.8,
        reason: '可能是项目合作咨询',
      });
      expect(shouldIntercept(c, env, 'some text')).toBe(false);
    });

    it('intercepts high-confidence ad even with business reason', () => {
      const env = makeEnv({ FILTER_THRESHOLD: '0.75' });
      const c = makeClassification({
        category: 'ad',
        confidence: 0.85,
        reason: '可能是项目合作咨询',
      });
      // isLowRiskBusinessOpening returns true, but confidence >= 0.85
      // so the bypass does NOT apply
      expect(shouldIntercept(c, env, 'some text')).toBe(true);
    });
  });

  describe('edge cases', () => {
    it('handles empty text', () => {
      const env = makeEnv();
      const c = makeClassification({ category: 'spam', confidence: 0.9 });
      // Empty text → isBusinessOpeningText returns false (regex needs content)
      expect(shouldIntercept(c, env, '')).toBe(true);
    });

    it('handles confidence exactly 0', () => {
      const env = makeEnv({ FILTER_THRESHOLD: '0' });
      const c = makeClassification({ category: 'spam', confidence: 0 });
      expect(shouldIntercept(c, env, 'spam')).toBe(true);
    });

    it('handles confidence above 1 (defensive)', () => {
      const env = makeEnv({ FILTER_THRESHOLD: '0.75' });
      const c = makeClassification({ category: 'spam', confidence: 1.5 });
      expect(shouldIntercept(c, env, 'spam')).toBe(true);
    });

    it('handles invalid threshold gracefully (NaN)', () => {
      const env = makeEnv({ FILTER_THRESHOLD: 'not-a-number' });
      const c = makeClassification({ category: 'spam', confidence: 0.5 });
      // Number('not-a-number') === NaN, NaN comparison is always false
      // so confidence >= NaN is false, so shouldIntercept returns false
      expect(shouldIntercept(c, env, 'spam')).toBe(false);
    });
  });
});
