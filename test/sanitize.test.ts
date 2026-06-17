import { describe, it, expect } from 'vitest';
import {
  redactPII,
  truncateForAI,
  isValidModelName,
  isValidUid,
  detectSuspiciousDraft,
  stripControlChars,
  sanitizeForLog,
} from '../src/sanitize';

describe('sanitize', () => {
  describe('redactPII', () => {
    it('redacts Chinese mobile numbers', () => {
      expect(redactPII('我的电话 13812345678')).toBe('我的电话 [PHONE]');
    });
    it('does not redact short digit sequences', () => {
      expect(redactPII('订单号 12345')).toBe('订单号 12345');
    });
    it('redacts email addresses', () => {
      expect(redactPII('联系 abc@example.com 谢谢')).toBe('联系 [EMAIL] 谢谢');
    });
    it('redacts API keys (sk- prefix)', () => {
      expect(redactPII('key: sk-abcdefghijklmnopqrstuvwxyz123456')).toBe('key: [API-KEY]');
    });
    it('redacts API keys (BSA prefix)', () => {
      expect(redactPII('BSAabcdefghijklmnopqrstuvwxyz123456')).toBe('[API-KEY]');
    });
    it('redacts API keys (tvly- prefix)', () => {
      expect(redactPII('tvly-abcdefghijklmnopqrstuvwxyz123456')).toBe('[API-KEY]');
    });
    it('redacts 18-digit ID card numbers', () => {
      expect(redactPII('身份证 11010519491231002X')).toBe('身份证 [ID]');
    });
    it('handles empty input', () => {
      expect(redactPII('')).toBe('');
    });
    it('does not redact normal text', () => {
      expect(redactPII('你好，我想咨询一下项目合作')).toBe('你好，我想咨询一下项目合作');
    });
  });

  describe('truncateForAI', () => {
    it('returns short text unchanged', () => {
      expect(truncateForAI('hello', 100)).toBe('hello');
    });
    it('truncates long text and appends marker', () => {
      const long = 'a'.repeat(200);
      const result = truncateForAI(long, 100);
      expect(result.length).toBe(100 + '\n[...truncated]'.length);
      expect(result.endsWith('[...truncated]')).toBe(true);
    });
    it('handles empty input', () => {
      expect(truncateForAI('', 100)).toBe('');
    });
    it('default max is 1500', () => {
      const long = 'a'.repeat(2000);
      const result = truncateForAI(long);
      expect(result.length).toBe(1500 + '\n[...truncated]'.length);
    });
  });

  describe('isValidModelName', () => {
    it('accepts common model names', () => {
      expect(isValidModelName('gpt-4o-mini')).toBe(true);
      expect(isValidModelName('gpt-4')).toBe(true);
      expect(isValidModelName('claude-3-5-sonnet')).toBe(true);
      expect(isValidModelName('@cf/meta/llama-3.3-70b')).toBe(true);
      expect(isValidModelName('deepseek-chat')).toBe(true);
    });
    it('rejects names with spaces', () => {
      expect(isValidModelName('gpt 4')).toBe(false);
    });
    it('rejects empty names', () => {
      expect(isValidModelName('')).toBe(false);
    });
    it('rejects names with special chars', () => {
      expect(isValidModelName('gpt-4; rm -rf /')).toBe(false);
      expect(isValidModelName('gpt-4\ninjection')).toBe(false);
      expect(isValidModelName('gpt-4`whoami`')).toBe(false);
    });
    it('rejects names longer than 100 chars', () => {
      expect(isValidModelName('a'.repeat(101))).toBe(false);
    });
  });

  describe('isValidUid', () => {
    it('accepts typical Telegram UIDs', () => {
      expect(isValidUid(123456789)).toBe(true);
      expect(isValidUid('123456789')).toBe(true);
      expect(isValidUid(1)).toBe(true);
    });
    it('rejects 0 and negative', () => {
      expect(isValidUid(0)).toBe(false);
      expect(isValidUid(-1)).toBe(false);
    });
    it('rejects non-integer', () => {
      expect(isValidUid(1.5)).toBe(false);
      expect(isValidUid('abc')).toBe(false);
    });
    it('accepts uids near current Telegram range (8e9)', () => {
      expect(isValidUid(8000000000)).toBe(true);
      expect(isValidUid(15000000000)).toBe(true);
    });
    it('rejects uids beyond 2e10', () => {
      expect(isValidUid(3e10)).toBe(false);
    });
  });

  describe('detectSuspiciousDraft', () => {
    it('detects Telegram links', () => {
      expect(detectSuspiciousDraft('加我 https://t.me/scammer')).toBe('contains_telegram_link');
      expect(detectSuspiciousDraft('t.me/abc')).toBe('contains_telegram_link');
    });
    it('detects @username mentions (5+ chars)', () => {
      expect(detectSuspiciousDraft('联系 @scammer123')).toBe('contains_username_mention');
    });
    it('does not flag short @mentions (under 5 chars)', () => {
      // @abc is 3 chars after @, below the 4-char threshold (regex is {4,})
      expect(detectSuspiciousDraft('@abc')).toBeNull();
    });
    it('detects crypto keywords', () => {
      expect(detectSuspiciousDraft('请把助记词发给我')).toBe('crypto_keywords');
      expect(detectSuspiciousDraft('my wallet address')).toBe('crypto_keywords');
      expect(detectSuspiciousDraft('private key here')).toBe('crypto_keywords');
    });
    it('detects payment keywords', () => {
      expect(detectSuspiciousDraft('请转账 100 USDT')).toBe('payment_keywords');
      expect(detectSuspiciousDraft('支付宝收款')).toBe('payment_keywords');
    });
    it('detects group invites', () => {
      expect(detectSuspiciousDraft('加群领红包')).toBe('group_invite');
      expect(detectSuspiciousDraft('QQ群：12345')).toBe('group_invite');
    });
    it('detects IP addresses', () => {
      expect(detectSuspiciousDraft('服务器 192.168.1.1')).toBe('contains_ip_address');
    });
    it('detects suspicious TLDs', () => {
      expect(detectSuspiciousDraft('访问 https://scam.top')).toBe('contains_suspicious_domain');
      expect(detectSuspiciousDraft('free-bitcoin.xyz')).toBe('contains_suspicious_domain');
    });
    it('returns null for clean drafts', () => {
      expect(detectSuspiciousDraft('好的，我会明天联系你')).toBeNull();
      expect(detectSuspiciousDraft('感谢您的咨询，我们会尽快回复')).toBeNull();
    });
    it('returns null for empty draft', () => {
      expect(detectSuspiciousDraft('')).toBeNull();
    });
  });

  describe('stripControlChars', () => {
    it('removes zero-width chars', () => {
      expect(stripControlChars('hello\u200Bworld')).toBe('helloworld');
    });
    it('removes BOM', () => {
      expect(stripControlChars('\uFEFFhello')).toBe('hello');
    });
    it('preserves normal whitespace', () => {
      expect(stripControlChars('hello world\n\ttab')).toBe('hello world\n\ttab');
    });
    it('handles empty input', () => {
      expect(stripControlChars('')).toBe('');
    });
  });

  describe('sanitizeForLog', () => {
    it('redacts PII and truncates', () => {
      const input = `电话 13812345678 ${'x'.repeat(600)}`;
      const result = sanitizeForLog(input, 100);
      expect(result).toContain('[PHONE]');
      expect(result.length).toBeLessThanOrEqual(103); // 100 + '...'
      expect(result.endsWith('...')).toBe(true);
    });
    it('combines strip + redact', () => {
      expect(sanitizeForLog('hello\u200B 13812345678')).toBe('hello [PHONE]');
    });
  });
});
