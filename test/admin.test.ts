import { describe, it, expect } from 'vitest';
import { sliceByUtf8Bytes } from '../src/admin';

describe('sliceByUtf8Bytes', () => {
  it('returns short strings unchanged', () => {
    expect(sliceByUtf8Bytes('hello', 100)).toBe('hello');
  });

  it('returns short ASCII unchanged when under limit', () => {
    expect(sliceByUtf8Bytes('abc', 10)).toBe('abc');
  });

  it('slices ASCII by byte count', () => {
    expect(sliceByUtf8Bytes('hello', 3)).toBe('hel');
    expect(sliceByUtf8Bytes('hello', 5)).toBe('hello');
  });

  it('slices Chinese (3 bytes per char)', () => {
    // 你 = 3 bytes, 好 = 3 bytes, total 6 bytes
    expect(sliceByUtf8Bytes('你好', 6)).toBe('你好');
    expect(sliceByUtf8Bytes('你好', 3)).toBe('你');
  });

  it('does NOT split a multi-byte char in the middle', () => {
    // 你 = 3 bytes. With maxBytes=4, we can fit 你 (3 bytes) but not 你好 (6 bytes).
    // Should return 你 (3 bytes), not 你 + half of 好.
    const result = sliceByUtf8Bytes('你好', 4);
    expect(result).toBe('你');
    // Verify byte length
    expect(new TextEncoder().encode(result).length).toBeLessThanOrEqual(4);
  });

  it('handles mixed ASCII and Chinese', () => {
    // "a你" = 1 + 3 = 4 bytes
    expect(sliceByUtf8Bytes('a你', 4)).toBe('a你');
    expect(sliceByUtf8Bytes('a你', 3)).toBe('a');
    expect(sliceByUtf8Bytes('a你', 2)).toBe('a');
    expect(sliceByUtf8Bytes('a你', 1)).toBe('a');
  });

  it('handles empty input', () => {
    expect(sliceByUtf8Bytes('', 100)).toBe('');
  });

  it('handles maxBytes=0', () => {
    expect(sliceByUtf8Bytes('hello', 0)).toBe('');
  });

  it('handles very long input', () => {
    const long = 'x'.repeat(10000);
    const result = sliceByUtf8Bytes(long, 100);
    expect(result.length).toBe(100);
    expect(new TextEncoder().encode(result).length).toBe(100);
  });

  it('handles emoji (4 bytes each)', () => {
    // 😀 = 4 bytes
    expect(sliceByUtf8Bytes('😀😀', 8)).toBe('😀😀');
    expect(sliceByUtf8Bytes('😀😀', 4)).toBe('😀');
    expect(sliceByUtf8Bytes('😀😀', 5)).toBe('😀');
  });

  it('respects exact byte boundary with Chinese', () => {
    // 你好世界 = 12 bytes (3+3+3+3)
    const s = '你好世界';
    expect(sliceByUtf8Bytes(s, 12)).toBe('你好世界');
    expect(sliceByUtf8Bytes(s, 11)).toBe('你好世');
    expect(sliceByUtf8Bytes(s, 9)).toBe('你好世');
    expect(sliceByUtf8Bytes(s, 6)).toBe('你好');
    // 5 bytes can only fit 你 (3 bytes), not 你好 (6 bytes)
    expect(sliceByUtf8Bytes(s, 5)).toBe('你');
    expect(sliceByUtf8Bytes(s, 4)).toBe('你');
    expect(sliceByUtf8Bytes(s, 3)).toBe('你');
  });

  it('never returns a string whose UTF-8 encoding exceeds maxBytes', () => {
    // Fuzz test: random strings and random maxBytes, verify invariant.
    const encoder = new TextEncoder();
    const chars = 'abcdefghij你好世界😀😂🤔';
    for (let trial = 0; trial < 200; trial++) {
      let s = '';
      const len = Math.floor(Math.random() * 20);
      for (let i = 0; i < len; i++) {
        s += chars[Math.floor(Math.random() * chars.length)];
      }
      const maxBytes = Math.floor(Math.random() * 30);
      const result = sliceByUtf8Bytes(s, maxBytes);
      const actualBytes = encoder.encode(result).length;
      // Invariant: result must never exceed maxBytes
      expect(actualBytes).toBeLessThanOrEqual(maxBytes);
      // Invariant: result must be a prefix of s (no character corruption)
      expect(s.startsWith(result)).toBe(true);
    }
  });
});
