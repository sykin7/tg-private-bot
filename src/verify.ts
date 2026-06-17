import type { Env, UserProfile } from './types';
import { Store } from './store';
import { Telegram } from './telegram';

function randomIntInclusive(min: number, max: number): number {
  const range = max - min + 1;
  const maxUnbiased = Math.floor(0xffffffff / range) * range;
  const buffer = new Uint32Array(1);
  let value: number;
  do {
    crypto.getRandomValues(buffer);
    value = buffer[0];
  } while (value >= maxUnbiased);
  return min + (value % range);
}

// SECURITY FIX (C2): cap verify attempts to prevent brute force.
const MAX_VERIFY_TRIES = 5;

// FIX P-anti-brute: GLOBAL_VERIFY_FAIL_LIMIT is enforced in store.ts.

// FIX P13: SHA-256 instead of SHA-1.
async function sha256(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

// FIX Q7: keep numbers small enough that any human can solve mentally in <3s.
// Range 2..15 (sum 4..30) is trivial for humans but still has 27 possible
// answers — combined with rate limit + global fail counter, brute force is
// impractical (10/24h attempts vs 27 answers ≈ 37% success rate per day).
//
// FIX Q8: AI defense. Pure arithmetic is solved by any LLM in <100ms. To add
// friction for AI solvers without making it hard for humans, we prepend a
// SHORT natural-language instruction that requires minimal comprehension:
//   "请发送【验证码】：13 + 27 = ?"
// The "验证码" keyword forces the AI to recognize this is a verification
// context (not just a math question), and the bracketed format makes naive
// "extract numbers, add them" bots slightly more likely to fail. This is
// NOT a real defense against modern LLMs — the real defense is the rate
// limit + fail counter making brute force economically infeasible.
//
// For higher security, set VERIFY_MODE=quiz and provide a custom Q&A that
// requires domain knowledge (e.g. "本店招牌菜是什么？查看简介后回答").

const MATH_OPERATORS = ['+', '加', '加上', 'plus'];

function pickOperator(): string {
  return MATH_OPERATORS[randomIntInclusive(0, MATH_OPERATORS.length - 1)];
}

// FIX Q7: normalize answer to handle user input variations.
// Accepts: "40", " 40 ", "40\n", "４０" (full-width).
// Rejects: "四十", "4e1", "0x28", "40.0" (too creative — keeps answer space tight).
// Exported for testing.
// FIX TEST-1: handle empty string explicitly. Number('') === 0 in JS, so
// without this guard, normalizeAnswer('') would return '0' — matching any
// challenge whose answer is 0 (theoretical for sum 0..0). Guard returns ''
// for empty input, which will never match a real answer hash.
// FIX TEST-3: reject scientific notation (4e1) and hex (0x28) which would
// expand the answer space and weaken brute-force protection. Only accept
// plain decimal integers with optional leading + and trailing .0.
export function normalizeAnswer(text: string): string {
  const trimmed = text.trim();
  if (trimmed === '') return '';
  // Convert full-width digits to half-width
  let s = trimmed.replace(/[\uFF10-\uFF19]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) - 0xFEE0));
  // Strip optional trailing .0 / .000 (treat "40.0" as "40") — but ONLY if
  // the rest is a plain integer. "4e1.0" won't match the integer regex below.
  s = s.replace(/\.0+$/, '');
  if (s === '') return '';
  // Strict integer pattern: optional +, then digits only. Rejects:
  //   - scientific notation (4e1)
  //   - hex (0x28)
  //   - decimals with non-zero fractional part (40.5)
  //   - expressions (1+1)
  //   - Chinese numerals (四十)
  if (!/^\+?\d+$/.test(s)) return s; // fallback: return as-is (won't match hash)
  return String(Math.trunc(Number(s)));
}

// Starts/continues first-time human verification. Returns true if the user is verified.
export async function ensureVerified(
  profile: UserProfile,
  text: string,
  env: Env,
  store: Store,
  tg: Telegram,
): Promise<boolean> {
  if (profile.verified) return true;

  // Empty text = caller wants a fresh challenge issued (used by /start flow).
  if (text.trim() === '') {
    await store.clearVerify(profile.id);
    await issueChallenge(profile, env, store, tg);
    return false;
  }

  // FIX Q12: /start inside ensureVerified NO LONGER triggers a fresh challenge.
  // The /start handler in index.ts is the only place that can reset verify
  // state, and it now enforces rate limit BEFORE resetting. If /start reaches
  // here (only happens if caller forgot to handle it), we treat it as a wrong
  // answer to consume an attempt. This blocks the "/start reset loop" attack.
  if (text.trim() === '/start') {
    // Record failure and bump tries — don't reset.
    const pending = await store.getVerify(profile.id);
    if (!pending) {
      // No active challenge — issue one (first contact). This is the only
      // legitimate /start path: user just started the bot, no challenge yet.
      await issueChallenge(profile, env, store, tg);
      return false;
    }
    // Active challenge exists — treat /start as a wrong answer to prevent
    // infinite reset loops. Bump tries without revealing the answer.
    await store.recordVerifyFailure(profile.id);
    await store.bumpVerifyTries(profile.id, pending);
    await tg.sendMessage(
      profile.id,
      '⚠️ 已有进行中的验证题，请直接发送数字答案。如需重新出题，请等待当前 5 次机会用完（每次失败后可重试）。',
    ).catch(() => {});
    return false;
  }

  const pending = await store.getVerify(profile.id);

  // No challenge yet -> issue one.
  if (!pending) {
    await issueChallenge(profile, env, store, tg);
    return false;
  }

  // FIX P-anti-brute: check GLOBAL verify-failure count first.
  const globalFails = await store.getVerifyFailureCount(profile.id);
  if (store.isVerifyFailureLimitExceeded(globalFails)) {
    await store.block(profile.id, `global verify fail limit (${globalFails})`, 'auto');
    await tg.sendMessage(
      profile.id,
      '🚫 您的账号在 24 小时内验证失败次数过多，已被自动封禁。如为误封，请通过其他渠道联系管理员。',
    ).catch(() => {});
    await store.clearVerify(profile.id);
    await store.clearVerifyFailures(profile.id);
    await tg
      .sendMessage(
        env.ADMIN_UID,
        `🛡️ 全局验证失败上限触发自动封禁\nuid:${profile.id}\n24h 内失败次数:${globalFails}`,
      )
      .catch(() => {});
    return false;
  }

  // SECURITY FIX (C2): enforce per-challenge attempt cap.
  if (pending.tries >= MAX_VERIFY_TRIES) {
    await store.recordVerifyFailure(profile.id);
    await store.block(profile.id, 'verify brute force (per-challenge)', 'auto');
    await tg.sendMessage(
      profile.id,
      '🚫 验证尝试次数过多，已自动封禁。如为误封，请说明情况后等待管理员处理。',
    ).catch(() => {});
    await store.clearVerify(profile.id);
    await tg
      .sendMessage(
        env.ADMIN_UID,
        `🛡️ 验证暴力破解触发自动封禁\nuid:${profile.id}\n本次尝试次数:${pending.tries}`,
      )
      .catch(() => {});
    return false;
  }

  // FIX Q7: normalize answer before hashing to accept user input variations.
  const normalizedUserInput = normalizeAnswer(text);
  const answerHash = await sha256(normalizedUserInput);
  if (answerHash === pending.answerHash) {
    profile.verified = true;
    await store.saveUser(profile);
    await store.clearVerify(profile.id);
    await store.clearVerifyFailures(profile.id);
    await tg.sendMessage(profile.id, '✅ 验证通过，请发送你的消息。').catch(() => {});
    return false; // this message was the answer, not real content
  }

  // FIX P-anti-brute: record failure in global counter.
  await store.recordVerifyFailure(profile.id);
  await store.bumpVerifyTries(profile.id, pending);
  const remaining = MAX_VERIFY_TRIES - pending.tries - 1;
  await tg.sendMessage(
    profile.id,
    `❌ 答案不对，请再试一次。剩余尝试次数：${remaining}。如果看不到题目，请直接发送数字答案。`,
  ).catch(() => {});
  return false;
}

// FIX P7: wrap issueChallenge's Telegram sendMessage in try/catch.
async function issueChallenge(profile: UserProfile, env: Env, store: Store, tg: Telegram): Promise<void> {
  const mode = env.VERIFY_MODE || 'math';
  if (mode === 'quiz' && env.VERIFY_QUESTION && env.VERIFY_ANSWER) {
    const answerHash = await sha256(env.VERIFY_ANSWER.trim());
    await store.setVerifyAnswer(profile.id, answerHash);
    await tg.sendMessage(profile.id, `请回答以下问题完成验证：\n${env.VERIFY_QUESTION}`).catch((e) => {
      console.warn('issueChallenge (quiz) sendMessage failed', (e as Error).message);
    });
    return;
  }
  // FIX Q7: smaller numbers (2..15) for human-friendliness.
  // 27 possible sums (4..30). Combined with 5/27 per-challenge cap and 10/24h
  // global fail cap, brute-force success rate per attacker per day ≈ 37%.
  // For higher security, set VERIFY_MODE=quiz and provide a custom Q&A.
  const a = randomIntInclusive(2, 15);
  const b = randomIntInclusive(2, 15);
  const op = pickOperator();
  const answerHash = await sha256(String(a + b));
  await store.setVerifyAnswer(profile.id, answerHash);
  // FIX Q8: "验证码" prefix forces AI to recognize verification context.
  await tg.sendMessage(
    profile.id,
    `请发送【验证码】：${a} ${op} ${b} = ?\n（直接发送数字答案）`,
  ).catch((e) => {
    console.warn('issueChallenge (math) sendMessage failed', (e as Error).message);
  });
}
