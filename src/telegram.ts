import type { TgUser } from './types';
import { escapeHtml } from './format';

const API = 'https://api.telegram.org/bot';

// FIX P34: default timeout for all Telegram API calls.
// CF Workers free tier caps ctx.waitUntil at ~30s wall-clock, so 15s leaves
// room for retry / fallback. Set to 0 to disable.
const TG_CALL_TIMEOUT_MS = 15000;

export class Telegram {
  constructor(private token: string) {}

  private async call<T = unknown>(method: string, body: Record<string, unknown>): Promise<T> {
    // FIX P34: enforce a per-call timeout so a slow Telegram API can't hang
    // the entire request. AbortController is the only way on Workers.
    const controller = new AbortController();
    const timeout = TG_CALL_TIMEOUT_MS > 0
      ? setTimeout(() => controller.abort(), TG_CALL_TIMEOUT_MS)
      : null;
    let res: Response;
    try {
      res = await fetch(`${API}${this.token}/${method}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal ?? undefined,
      });
    } catch (e) {
      if (controller.signal.aborted) {
        throw new Error(`Telegram ${method} timed out after ${TG_CALL_TIMEOUT_MS}ms`);
      }
      throw new Error(`Telegram ${method} network error: ${(e as Error).message}`);
    } finally {
      if (timeout) clearTimeout(timeout);
    }

    let json: { ok: boolean; result?: T; description?: string };
    try {
      json = (await res.json()) as { ok: boolean; result?: T; description?: string };
    } catch {
      throw new Error(`Telegram ${method} returned non-JSON (status ${res.status})`);
    }
    if (!json.ok) throw new Error(`Telegram ${method} failed: ${json.description}`);
    return json.result as T;
  }

  sendMessage(chatId: number | string, text: string, extra: Record<string, unknown> = {}) {
    return this.call<{ message_id: number }>('sendMessage', { chat_id: chatId, text, ...extra });
  }

  // SECURITY FIX (L5): preserve parse_mode and reply_parameters across chunks
  async sendLong(chatId: number | string, text: string, extra: Record<string, unknown> = {}): Promise<void> {
    const MAX = 4000;
    if (text.length <= MAX) {
      await this.sendMessage(chatId, text, extra);
      return;
    }
    for (let i = 0; i < text.length; i += MAX) {
      await this.sendMessage(chatId, text.slice(i, i + MAX), extra);
    }
  }

  editMessageText(chatId: number | string, messageId: number, text: string, extra: Record<string, unknown> = {}) {
    return this.call('editMessageText', { chat_id: chatId, message_id: messageId, text, ...extra });
  }

  copyMessage(toChatId: number | string, fromChatId: number | string, messageId: number, extra: Record<string, unknown> = {}) {
    return this.call<{ message_id: number }>('copyMessage', {
      chat_id: toChatId,
      from_chat_id: fromChatId,
      message_id: messageId,
      ...extra,
    });
  }

  forwardMessage(toChatId: number | string, fromChatId: number | string, messageId: number) {
    return this.call<{ message_id: number }>('forwardMessage', {
      chat_id: toChatId,
      from_chat_id: fromChatId,
      message_id: messageId,
    });
  }

  answerCallbackQuery(id: string, text?: string) {
    return this.call('answerCallbackQuery', { callback_query_id: id, text });
  }

  setMyCommands(commands: { command: string; description: string }[], scope?: Record<string, unknown>) {
    return this.call('setMyCommands', { commands, ...(scope ? { scope } : {}) });
  }

  setWebhook(url: string, secretToken: string) {
    return this.call('setWebhook', {
      url,
      secret_token: secretToken,
      allowed_updates: ['message', 'edited_message', 'callback_query'],
    });
  }

  deleteWebhook() {
    return this.call('deleteWebhook', {});
  }

  getMe() {
    return this.call<TgUser>('getMe', {});
  }
}

export function displayName(u?: TgUser): string {
  if (!u) return '(unknown)';
  const name = [u.first_name, u.last_name].filter(Boolean).join(' ');
  return name || u.username || `(uid:${u.id})`;
}

// FIX P39: HTML-escape user-controlled display name and username so that
// users can't inject HTML tags via their first_name / last_name / username.
export function senderHeader(u?: TgUser): string {
  if (!u) return '👤 (unknown)';
  const rawName = [u.first_name, u.last_name].filter(Boolean).join(' ');
  const name = rawName || u.username || `(uid:${u.id})`;
  const at = u.username ? ` @${escapeHtml(u.username)}` : '';
  return `👤 ${escapeHtml(name)}${at} (uid:${u.id})`;
}
