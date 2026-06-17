import type { Env, TgMessage } from './types';
import { Store } from './store';
import { Telegram } from './telegram';
import { handleAssistant, handleGhostwrite } from './assistant';
import { listModels } from './ai-filter';
import { isValidModelName, isValidUid } from './sanitize';

// Handles messages coming from the admin's private chat with the bot.
export async function handleAdminMessage(
  msg: TgMessage,
  env: Env,
  store: Store,
  tg: Telegram,
): Promise<void> {
  const adminId = env.ADMIN_UID;
  const adminUidNum = Number(adminId);
  const text = (msg.text ?? msg.caption ?? '').trim();
  const replied = msg.reply_to_message;

  // /aimode on|off
  // FIX S4/S5: use word-boundary matching to prevent /ban matching /bank,
  // /model matching /modeling, /ai matching /airplane, etc.
  // FIX S8: also support @bot suffix that Telegram clients may append.
  // Each command must be followed by space, end-of-string, or @botname.
  if (text === '/aimode' || text.startsWith('/aimode ') || text.startsWith('/aimode@')) {
    const arg = text.replace(/^\/aimode(?:@\w+)?\s*/, '').trim().toLowerCase();
    if (arg === 'on') {
      await store.setAdminAiMode(true);
      await tg.sendMessage(adminId, '✅ 已进入 AI 模式。之后直接发普通消息就是和助理聊天；/aimode off 退出。');
      return;
    }
    if (arg === 'off') {
      await store.setAdminAiMode(false);
      await tg.sendMessage(adminId, '✅ 已退出 AI 模式。');
      return;
    }
    const on = await store.getAdminAiMode();
    await tg.sendMessage(adminId, `AI 模式：${on ? '开启' : '关闭'}\n用法：/aimode on 或 /aimode off`);
    return;
  }

  // /intercepts [n]
  if (text === '/intercepts' || text.startsWith('/intercepts ') || text.startsWith('/intercepts@')) {
    const limitMatch = text.match(/\b(\d{1,2})\b/);
    const limit = limitMatch ? Number(limitMatch[1]) : 10;
    const items = await store.getInterceptedIndex(limit);
    if (!items.length) {
      await tg.sendMessage(adminId, '暂无拦截记录。');
      return;
    }
    const lines = items.map((item, index) => {
      const time = new Date(item.time).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
      const confidence = typeof item.confidence === 'number' ? item.confidence.toFixed(2) : '-';
      return `${index + 1}. uid:${item.userId} | ${item.category} | ${item.provider} | 置信:${confidence} | 次数:${item.violationCount ?? '-'}\n${time}\n原因：${item.reason}\n内容：${item.text.slice(0, 120)}`;
    });
    await tg.sendLong(adminId, `最近拦截记录：\n\n${lines.join('\n\n')}`);
    return;
  }

  // SECURITY FIX (M1): /audit command to view admin action log
  if (text === '/audit' || text.startsWith('/audit ') || text.startsWith('/audit@')) {
    const limitMatch = text.match(/\b(\d{1,3})\b/);
    const limit = limitMatch ? Number(limitMatch[1]) : 20;
    const log = await store.getAuditLog(limit);
    if (!log.length) {
      await tg.sendMessage(adminId, '暂无审计记录。');
      return;
    }
    const lines = log.map((entry, i) => {
      const time = new Date(entry.time).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
      return `${i + 1}. [${time}] actor:${entry.actor} | ${entry.action} | ${entry.target}\n   ${entry.detail}`;
    });
    await tg.sendLong(adminId, `审计日志：\n\n${lines.join('\n\n')}`);
    return;
  }

  // /ban /unban /block /unblock /forgive
  // FIX S4: exact command matching to prevent /ban matching /bank etc.
  // FIX S8: support @bot suffix.
  const banMatch = text.match(/^\/(?:ban|unban|block|unblock|forgive)(?:@\w+)?(?:\s|$)/);
  if (banMatch) {
    // SECURITY FIX (H3): strict uid parsing — uid must immediately follow command
    const uid = await targetUid(text, replied, store);
    if (!uid) {
      await tg.sendMessage(adminId, '用法：reply 用户消息后发 /ban，或 /ban <uid>；解封用 /unban <uid>；清空计数用 /forgive <uid>');
      return;
    }
    if (!isValidUid(uid)) {
      await tg.sendMessage(adminId, `⚠️ 无效的 uid: ${uid}`);
      return;
    }
    if (text.startsWith('/unblock') || text.startsWith('/unban')) {
      await store.unblock(uid);
      await store.logAdminAction(adminUidNum, 'unban', `uid:${uid}`, text.slice(0, 200));
      await tg.sendMessage(adminId, `已解封 uid:${uid}`);
      return;
    }
    if (text.startsWith('/forgive')) {
      await store.clearViolations(uid);
      await store.clearAppeals(uid);
      await store.logAdminAction(adminUidNum, 'forgive', `uid:${uid}`, text.slice(0, 200));
      await tg.sendMessage(adminId, `已清空 uid:${uid} 的违规/申诉计数。`);
      return;
    }
    await store.block(uid, 'manual ban', 'manual');
    await store.logAdminAction(adminUidNum, 'ban', `uid:${uid}`, text.slice(0, 200));
    await tg.sendMessage(adminId, `已拉黑 uid:${uid}`);
    return;
  }

  // /model
  // FIX S4: exact command matching to prevent /model matching /modeling.
  // FIX S8: support @bot suffix.
  if (text === '/model' || text.startsWith('/model ') || text.startsWith('/model@')) {
    const arg = text.replace(/^\/model(?:@\w+)?\s*/, '').trim();
    if (!arg) {
      const cur = (await store.getActiveModel()) || env.AI_MODEL;
      await tg.sendMessage(
        adminId,
        `当前模型：${cur}\n用法：\n/model list 查看可用模型\n/model <模型名> 切换\n/model default 恢复默认(${env.AI_MODEL})`,
      );
      return;
    }
    if (arg === 'list') {
      const models = await listModels(env);
      if (!models.length) {
        await tg.sendMessage(adminId, '未能获取模型列表（检查 AI_BASE_URL / AI_API_KEY，或中转站不支持 /models）。');
        return;
      }
      const cur = (await store.getActiveModel()) || env.AI_MODEL;
      const list = models.map((m) => (m === cur ? `• ${m}  ← 当前` : `• ${m}`)).join('\n');
      await tg.sendLong(adminId, `可用模型（共 ${models.length}）：\n${list}`);
      return;
    }
    if (arg === 'default') {
      await store.clearActiveModel();
      await store.logAdminAction(adminUidNum, 'model_default', '-', env.AI_MODEL);
      await tg.sendMessage(adminId, `已恢复默认模型：${env.AI_MODEL}`);
      return;
    }
    // SECURITY FIX (M10): validate model name to prevent injection
    if (!isValidModelName(arg)) {
      await tg.sendMessage(adminId, '⚠️ 无效的模型名（只允许字母、数字、点、横杠、斜杠、冒号，长度 ≤ 100）。');
      return;
    }
    await store.setActiveModel(arg);
    await store.logAdminAction(adminUidNum, 'model_switch', arg, text.slice(0, 100));
    await tg.sendMessage(adminId, `已切换模型为：${arg}`);
    return;
  }

  // /to <uid> <content>
  // FIX S4: exact match or space-after, to prevent /to matching /today etc.
  // FIX S8: support @bot suffix.
  if (text === '/to' || text.startsWith('/to ') || text.startsWith('/to@')) {
    // SECURITY FIX (H2): IDOR protection — only allow sending to known users
    const m = text.match(/^\/to(?:@\w+)?\s+(\d{5,})\s+([\s\S]+)$/);
    if (!m) {
      await tg.sendMessage(adminId, '用法：/to <uid> 内容');
      return;
    }
    const targetUid = Number(m[1]);
    if (!isValidUid(targetUid)) {
      await tg.sendMessage(adminId, `⚠️ 无效的 uid: ${targetUid}`);
      return;
    }
    if (targetUid === adminUidNum) {
      await tg.sendMessage(adminId, '⚠️ 不能用 /to 给自己发消息。');
      return;
    }
    const targetProfile = await store.getUser(targetUid);
    if (!targetProfile) {
      await tg.sendMessage(adminId, `⚠️ uid:${targetUid} 不是本 bot 的已知用户，拒绝发送（防止 IDOR 滥用）。`);
      return;
    }
    // FIX P19: Telegram sendMessage limits text to 4096 UTF-8 bytes (not chars).
    // Chinese chars are 3 bytes each, so 4000 chars × 3 = 12000 bytes > 4096.
    // Slice by UTF-8 byte length to avoid 400 Bad Request.
    const content = sliceByUtf8Bytes(m[2], 4000);
    // FIX P43: try sending to user; if it fails (bot blocked, user deleted account),
    // inform the admin instead of letting the error bubble up.
    try {
      await tg.sendMessage(targetUid, content);
    } catch (e) {
      await tg.sendMessage(
        adminId,
        `⚠️ 发送给 uid:${targetUid} 失败：${(e as Error).message}\n\n（用户可能已屏蔽 bot 或注销账号）`,
      );
      return;
    }
    await store.logAdminAction(adminUidNum, 'to_send', `uid:${targetUid}`, content.slice(0, 200));
    await tg.sendMessage(adminId, `✅ 已发送给 uid:${targetUid}`);
    return;
  }

  // /ai
  // FIX S5: exact match or space-after, to prevent /ai matching /airplane.
  // FIX S8: support @bot suffix.
  if (text === '/ai' || text.startsWith('/ai ') || text.startsWith('/ai@')) {
    const intent = text.replace(/^\/ai(?:@\w+)?\s*/, '').trim();
    if (!intent) {
      await tg.sendMessage(adminId, '用法：/ai <问题> 或 reply 转发消息后 /ai <意向>');
      return;
    }
    if (replied) {
      const uid = await store.resolveAdminMsg(replied.message_id);
      if (uid) {
        await handleGhostwrite(uid, intent, env, store, tg);
        return;
      }
      // SECURITY FIX (C4): mapping expired — tell admin how to proceed
      await tg.sendMessage(
        adminId,
        '⚠️ 这条转发消息的回复映射已过期（超过 30 天）。\n\n请直接用 /to <uid> <意向> 主动联系，或 reply 一条更近的转发消息。',
      );
      return;
    }
    await handleAssistant(intent, env, store, tg);
    return;
  }

  // Plain reply to a forwarded message -> relay back to that user.
  if (replied) {
    const uid = await store.resolveAdminMsg(replied.message_id);
    if (uid) {
      await tg.copyMessage(uid, msg.chat.id, msg.message_id);
      return;
    }
    // SECURITY FIX (C4): explicit fallback when mapping expires
    await tg.sendMessage(
      adminId,
      '⚠️ 这条转发消息的回复映射已过期（超过 30 天）。\n\n请用 /to <uid> <内容> 主动联系对方。',
    );
    return;
  }

  // AI mode: plain admin messages go to the assistant without needing /ai.
  if (text && !text.startsWith('/') && (await store.getAdminAiMode())) {
    await handleAssistant(text, env, store, tg);
    return;
  }

  await tg.sendMessage(adminId, 'ℹ️ 请 reply 某条转发消息来回复用户，或用 /to <uid> 指定对象，或 /ai <问题> 找助理。');
}

// SECURITY FIX (H3): strict uid parser — uid must come right after the command
// FIX S8: support @bot suffix.
async function targetUid(text: string, replied: TgMessage | undefined, store: Store): Promise<number | null> {
  const m = text.match(/^\/(?:ban|unban|block|unblock|forgive)(?:@\w+)?\s+(\d{5,})\b/);
  if (m) return Number(m[1]);
  if (replied) return store.resolveAdminMsg(replied.message_id);
  return null;
}

// FIX P19: slice string by UTF-8 byte length (Telegram text limit is 4096 bytes).
// Returns a string whose UTF-8 encoding is at most maxBytes bytes.
// Exported for testing.
export function sliceByUtf8Bytes(s: string, maxBytes: number): string {
  const encoder = new TextEncoder();
  const bytes = encoder.encode(s);
  if (bytes.length <= maxBytes) return s;
  // Find the largest substring whose UTF-8 encoding fits in maxBytes.
  // Use a simple binary search since TextDecoder can recover boundaries.
  let lo = 0;
  let hi = s.length;
  // Quick path: estimate by char count, then adjust.
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (encoder.encode(s.slice(0, mid)).length <= maxBytes) {
      lo = mid;
    } else {
      hi = mid - 1;
    }
  }
  return s.slice(0, lo);
}
