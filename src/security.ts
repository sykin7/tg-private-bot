// Shared security primitives used across the codebase.

import type { Env } from './types';

// Telegram's ASN on Cloudflare. Used for webhook origin verification.
// See https://core.telegram.org/bots/webhooks#ip-addresses
const TELEGRAM_ASN = 62041;

/**
 * Verify that the incoming request originates from Telegram's network.
 * Uses Cloudflare's cf.asn field which is reliable on the edge.
 *
 * Set BYPASS_TG_ASN_CHECK=1 in dev to bypass.
 */
export function isFromTelegram(request: Request, env: Env): boolean {
  // Allow bypass in dev
  if ((env.BYPASS_TG_ASN_CHECK ?? '') === '1') return true;

  const cf = (request as Request & { cf?: { asn?: number } }).cf;
  if (!cf || typeof cf.asn !== 'number') {
    // If cf.asn is unavailable (very unusual on Workers), fail open
    // but log it so admin can investigate.
    console.warn('cf.asn unavailable, failing open for webhook');
    return true;
  }
  return cf.asn === TELEGRAM_ASN;
}

/**
 * Compare two secret strings in constant time to prevent timing attacks.
 */
export function constantTimeEquals(a: string, b: string): boolean {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  if (a.length !== b.length) return false;

  const encoder = new TextEncoder();
  const bufA = encoder.encode(a);
  const bufB = encoder.encode(b);

  let diff = 0;
  for (let i = 0; i < bufA.length; i++) {
    diff |= bufA[i] ^ bufB[i];
  }
  return diff === 0;
}

/**
 * Verify the bot secret from either header (preferred) or query (legacy).
 */
export function verifyBotSecret(request: Request, env: Env, url: URL): boolean {
  const headerSecret = request.headers.get('x-bot-secret');
  if (headerSecret) {
    return constantTimeEquals(headerSecret, env.BOT_SECRET);
  }
  const querySecret = url.searchParams.get('secret');
  if (querySecret) {
    return constantTimeEquals(querySecret, env.BOT_SECRET);
  }
  return false;
}

/**
 * Verify the Telegram webhook signature header.
 */
export function verifyWebhookSecret(request: Request, env: Env): boolean {
  const headerSecret = request.headers.get('X-Telegram-Bot-Api-Secret-Token');
  if (!headerSecret) return false;
  return constantTimeEquals(headerSecret, env.BOT_SECRET);
}
