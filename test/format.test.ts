import { describe, it, expect } from 'vitest';
import { escapeHtml, formatTelegramHtml } from '../src/format';

describe('format', () => {
  describe('escapeHtml', () => {
    it('escapes & < > " \'', () => {
      expect(escapeHtml('<script>alert("x")</script>')).toBe(
        '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;',
      );
      expect(escapeHtml("it's & that's")).toBe('it&#39;s &amp; that&#39;s');
    });
    it('escapes & first (no double-escape)', () => {
      // & must be escaped first so we don't double-escape entities we just created
      expect(escapeHtml('&lt;')).toBe('&amp;lt;');
    });
    it('handles empty input', () => {
      expect(escapeHtml('')).toBe('');
    });
  });

  describe('formatTelegramHtml', () => {
    it('preserves plain text', () => {
      expect(formatTelegramHtml('hello world')).toBe('hello world');
    });
    it('escapes user HTML', () => {
      expect(formatTelegramHtml('<b>not bold</b>')).toBe('&lt;b&gt;not bold&lt;/b&gt;');
    });
    it('converts **bold** to <b>', () => {
      expect(formatTelegramHtml('this is **bold** text')).toBe('this is <b>bold</b> text');
    });
    it('converts `inline code` to <code>', () => {
      expect(formatTelegramHtml('use `npm install`')).toBe('use <code>npm install</code>');
    });
    it('converts ```fenced code``` to <pre>', () => {
      const result = formatTelegramHtml('```\ncode block\n```');
      expect(result).toBe('<pre>code block</pre>');
    });
    it('does NOT process **bold** inside code blocks (P38 fix)', () => {
      const result = formatTelegramHtml('```\n**not bold**\n```');
      expect(result).toBe('<pre>**not bold**</pre>');
      // Should NOT contain <b>
      expect(result).not.toContain('<b>');
    });
    it('does NOT process **bold** inside inline code (P38 fix)', () => {
      const result = formatTelegramHtml('see `**not bold**` here');
      expect(result).toBe('see <code>**not bold**</code> here');
      expect(result).not.toContain('<b>');
    });
    it('handles multiple code blocks', () => {
      const result = formatTelegramHtml('```\nblock1\n```\nmid\n```\nblock2\n```');
      expect(result).toBe('<pre>block1</pre>\nmid\n<pre>block2</pre>');
    });
    it('escapes HTML inside code blocks', () => {
      const result = formatTelegramHtml('```\n<div>test</div>\n```');
      expect(result).toBe('<pre>&lt;div&gt;test&lt;/div&gt;</pre>');
    });
    it('handles mixed formatting', () => {
      const result = formatTelegramHtml('**bold** and `code` and ```\nblock\n```');
      expect(result).toBe('<b>bold</b> and <code>code</code> and <pre>block</pre>');
    });
    it('handles empty input', () => {
      expect(formatTelegramHtml('')).toBe('');
    });
  });
});
