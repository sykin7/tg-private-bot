import type { Env } from './types';

// Keyword fallback used when AI is unavailable.
export function keywordHit(text: string, env: Env): boolean {
  const raw = (env.BLOCK_KEYWORDS || '').trim();
  if (!raw) return false;
  // SECURITY FIX (L9): also support comma as separator
  const words = raw.split(/[|\n,]/).map((w) => w.trim()).filter(Boolean);
  const lower = text.toLowerCase();
  return words.some((w) => lower.includes(w.toLowerCase()));
}

// SECURITY FIX: admin check uses string compare; this is fine because
// ADMIN_UID is now a secret, but we keep it strict.
export function isAdmin(env: Env, fromId?: number): boolean {
  if (!fromId) return false;
  return String(fromId) === String(env.ADMIN_UID);
}
