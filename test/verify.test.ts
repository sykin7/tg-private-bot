import { describe, it, expect } from 'vitest';
import { normalizeAnswer } from '../src/verify';

describe('verify normalizeAnswer', () => {
  it('preserves plain integers', () => {
    expect(normalizeAnswer('40')).toBe('40');
    expect(normalizeAnswer('0')).toBe('0');
    expect(normalizeAnswer('198')).toBe('198');
  });

  it('trims whitespace', () => {
    expect(normalizeAnswer('  40  ')).toBe('40');
    expect(normalizeAnswer('40\n')).toBe('40');
    expect(normalizeAnswer('\t40\t')).toBe('40');
  });

  it('converts full-width digits to half-width', () => {
    expect(normalizeAnswer('４０')).toBe('40');
    expect(normalizeAnswer('１２３')).toBe('123');
  });

  it('strips trailing .0', () => {
    expect(normalizeAnswer('40.0')).toBe('40');
    expect(normalizeAnswer('40.000')).toBe('40');
  });

  it('REJECTS decimal fractions (40.7, 40.999) — security fix', () => {
    // After TEST-3 fix, only plain integers + optional .0 are accepted.
    // 40.7 and 40.999 are returned as-is and won't match the hash of "40".
    expect(normalizeAnswer('40.7')).toBe('40.7');
    expect(normalizeAnswer('40.999')).toBe('40.999');
  });

  it('handles positive sign', () => {
    expect(normalizeAnswer('+40')).toBe('40');
  });

  it('returns original string for non-numeric input (fallback)', () => {
    expect(normalizeAnswer('forty')).toBe('forty');
    expect(normalizeAnswer('四十')).toBe('四十');
  });

  it('handles empty input', () => {
    expect(normalizeAnswer('')).toBe('');
  });

  // FIX TEST-3: reject scientific notation and hex to keep answer space tight.
  it('REJECTS scientific notation (4e1) — security fix', () => {
    // Previously Number('4e1') === 40, which would match answer 40.
    // Now we only accept plain decimal integers, so 4e1 returns as-is
    // and won't match the hash of "40".
    expect(normalizeAnswer('4e1')).toBe('4e1');
    expect(normalizeAnswer('4E1')).toBe('4E1');
  });

  it('REJECTS hex notation (0x28) — security fix', () => {
    expect(normalizeAnswer('0x28')).toBe('0x28');
  });

  it('REJECTS expressions (1+1) — security fix', () => {
    expect(normalizeAnswer('1+1')).toBe('1+1');
  });

  it('REJECTS decimal fractions (40.5) — security fix', () => {
    expect(normalizeAnswer('40.5')).toBe('40.5');
  });

  it('ACCEPTS trailing .0 (40.0 → 40) — user-friendliness', () => {
    expect(normalizeAnswer('40.0')).toBe('40');
    expect(normalizeAnswer('40.000')).toBe('40');
  });

  it('ACCEPTS leading + (+40 → 40)', () => {
    expect(normalizeAnswer('+40')).toBe('40');
  });
});
