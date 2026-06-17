import { describe, it, expect } from 'vitest';
import { constantTimeEquals } from '../src/security';

describe('security', () => {
  describe('constantTimeEquals', () => {
    it('returns true for equal strings', () => {
      expect(constantTimeEquals('hello', 'hello')).toBe(true);
      expect(constantTimeEquals('', '')).toBe(true);
      expect(constantTimeEquals('a-b-c-123', 'a-b-c-123')).toBe(true);
    });

    it('returns false for different strings', () => {
      expect(constantTimeEquals('hello', 'world')).toBe(false);
      expect(constantTimeEquals('hello', 'Hello')).toBe(false);
    });

    it('returns false for different lengths', () => {
      expect(constantTimeEquals('hello', 'hell')).toBe(false);
      expect(constantTimeEquals('hello', 'helloo')).toBe(false);
    });

    it('returns false for non-string inputs', () => {
      expect(constantTimeEquals(null as unknown as string, 'hello')).toBe(false);
      expect(constantTimeEquals('hello', null as unknown as string)).toBe(false);
      expect(constantTimeEquals(undefined as unknown as string, undefined as unknown as string)).toBe(false);
    });

    it('handles unicode correctly', () => {
      expect(constantTimeEquals('你好世界', '你好世界')).toBe(true);
      expect(constantTimeEquals('你好世界', '你好')).toBe(false);
      expect(constantTimeEquals('你好世界', '你好地球')).toBe(false);
    });

    it('handles special characters', () => {
      expect(constantTimeEquals('p@ss"w0rd!', 'p@ss"w0rd!')).toBe(true);
      expect(constantTimeEquals('p@ss"w0rd!', 'p@ss"w0rd?')).toBe(false);
    });
  });
});
