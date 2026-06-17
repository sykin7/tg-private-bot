// PII redaction and input sanitization utilities.
// Used to prevent leaking user personal data to AI relay stations,
// admin notifications, audit logs, and intercepted message storage.

const PHONE_RE = /(?<!\d)1[3-9]\d{9}(?!\d)/g;
const ID_CARD_RE = /(?<!\d)\d{17}[\dXx](?!\d)/g;
const EMAIL_RE = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g;
const API_KEY_RE = /\b(sk-[A-Za-z0-9]{20,}|BSA[A-Za-z0-9]{20,}|tvly-[A-Za-z0-9]{20,})\b/g;
const BANK_CARD_RE = /(?<!\d)\d{16,19}(?!\d)/g;

/**
 * Redact common Chinese PII patterns from text.
 * Returns a new string with sensitive patterns replaced.
 * Note: redaction is best-effort, not a security boundary.
 */
export function redactPII(text: string): string {
  if (!text) return '';
  return text
    .replace(API_KEY_RE, '[API-KEY]')
    .replace(ID_CARD_RE, '[ID]')
    .replace(PHONE_RE, '[PHONE]')
    .replace(EMAIL_RE, '[EMAIL]')
    .replace(BANK_CARD_RE, '[CARD]');
}

/**
 * Truncate user-supplied text before sending to AI relay.
 * Prevents abuse via oversized messages and reduces token cost.
 */
export function truncateForAI(text: string, maxChars = 1500): string {
  if (!text) return '';
  if (text.length <= maxChars) return text;
  return text.slice(0, maxChars) + '\n[...truncated]';
}

/**
 * Strict validation for AI model names.
 * Prevents injection via model parameter.
 * FIX B37: disallow spaces (model names never contain spaces).
 */
export function isValidModelName(name: string): boolean {
  if (!name || name.length > 100) return false;
  return /^[a-zA-Z0-9._\-\/:@]{1,100}$/.test(name);
}

/**
 * Strict validation for Telegram user IDs.
 * FIX B38: relax upper bound to 2e10 to future-proof (current uids near 8e9).
 */
export function isValidUid(uid: number | string): boolean {
  const n = typeof uid === 'string' ? Number(uid) : uid;
  return Number.isInteger(n) && n >= 1 && n <= 2e10;
}

/**
 * Detect suspicious patterns in AI-generated drafts.
 * Used as output-layer defense against prompt injection.
 *
 * Returns the first matched reason, or null if clean.
 * FIX B36: also detect IP addresses and bare domains that could be phishing.
 */
export function detectSuspiciousDraft(draft: string): string | null {
  if (!draft) return null;

  // Telegram invite links
  if (/t\.me\/\S+/i.test(draft)) return 'contains_telegram_link';
  // @username mentions (5+ chars after @ to avoid common words)
  if (/@[a-zA-Z][a-zA-Z0-9_]{4,}/.test(draft)) return 'contains_username_mention';
  // Crypto / wallet keywords
  if (/助记词|钱包|私钥|seed\s*phrase|wallet|private\s*key/i.test(draft)) return 'crypto_keywords';
  // Payment / transfer keywords
  if (/转账|付款|支付|USDT|BTC|支付宝|微信支付|银行卡/i.test(draft)) return 'payment_keywords';
  // QQ group / WeChat group invites
  if (/加群|扣群|QQ群|微信群/i.test(draft)) return 'group_invite';
  // FIX B36: IP addresses (potential phishing / C2)
  if (/\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/.test(draft)) return 'contains_ip_address';
  // FIX B36: bare domains with suspicious TLDs
  if (/\b[a-z0-9-]+\.(?:top|xyz|tk|ml|ga|cf|gq|click|zip|mov)\b/i.test(draft)) return 'contains_suspicious_domain';

  return null;
}

/**
 * Strip control characters that could be used to manipulate display.
 */
export function stripControlChars(text: string): string {
  if (!text) return '';
  // Remove zero-width chars, BOM, and other invisibles except normal whitespace
  return text.replace(/[\u0000-\u0008\u000B-\u001F\u007F-\u009F\u200B-\u200F\u2028-\u202F\uFEFF]/g, '');
}

/**
 * Sanitize user-supplied text for logging / display.
 * Combines stripControlChars + redactPII + length limit.
 */
export function sanitizeForLog(text: string, maxChars = 500): string {
  const cleaned = stripControlChars(text);
  const redacted = redactPII(cleaned);
  return redacted.length > maxChars ? redacted.slice(0, maxChars) + '...' : redacted;
}
