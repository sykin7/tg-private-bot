import type { Env, TgMessage } from './types';
import { Store } from './store';
import { Telegram, senderHeader } from './telegram';
import { escapeHtml } from './format';

// Abstraction over relay target so group/topic mode can be added later (RELAY_MODE=group).
export interface RelayTarget {
  deliverToAdmin(msg: TgMessage): Promise<void>;
}

class PrivateRelay implements RelayTarget {
  constructor(private env: Env, private store: Store, private tg: Telegram) {}

  async deliverToAdmin(msg: TgMessage): Promise<void> {
    const adminId = this.env.ADMIN_UID;
    const fromId = msg.from!.id;

    const typeTag = this.detectTypeTag(msg);
    const headerText = `${senderHeader(msg.from)}${typeTag}\n📋 UID: <code>${fromId}</code>`;
    let headerMsgId: number | null = null;
    try {
      const header = await this.tg.sendMessage(adminId, headerText, { parse_mode: 'HTML' });
      headerMsgId = header.message_id;
    } catch (e) {
      console.error('relay: failed to send header', (e as Error).message);
      return;
    }
    // FIX F6: mapAdminMsg failure is non-fatal. Header is already sent, so
    // admin sees the message. If mapping fails, admin can't reply via reply
    // but can still use /to <uid> (uid is in the header text).
    await this.store.mapAdminMsg(headerMsgId, fromId).catch((e) => {
      console.warn('relay: mapAdminMsg(header) failed (non-fatal)', (e as Error).message);
    });

    // Copy the actual content (text/photo/file/sticker...).
    try {
      const copied = await this.tg.copyMessage(adminId, msg.chat.id, msg.message_id);
      // FIX F6: same — mapping failure is non-fatal. Content was forwarded
      // successfully, admin can see it. Don't show "forward failed" message
      // when only the mapping failed.
      await this.store.mapAdminMsg(copied.message_id, fromId).catch((e) => {
        console.warn('relay: mapAdminMsg(content) failed (non-fatal)', (e as Error).message);
      });
    } catch (e) {
      // copyMessage itself failed (message deleted, content unsupported, etc.)
      console.warn('relay: copyMessage failed', (e as Error).message);
      try {
        await this.tg.editMessageText(
          adminId,
          headerMsgId!,
          `${headerText}\n\n⚠️ 原始内容转发失败：${(e as Error).message}`,
          { parse_mode: 'HTML' },
        );
      } catch {
        // editMessageText failed too — nothing more we can do.
      }
    }
  }

  private detectTypeTag(msg: TgMessage): string {
    // FIX P15: escape user-controlled file_name before inserting into HTML.
    if (msg.photo?.length) return ' [图片]';
    if (msg.document) {
      const name = msg.document.file_name ? `: ${escapeHtml(msg.document.file_name)}` : '';
      return ` [文件${name}]`;
    }
    if (msg.video) return ' [视频]';
    if (msg.voice) return ' [语音]';
    if (msg.audio) return ' [音频]';
    if (msg.sticker) return ` [贴纸${msg.sticker.emoji ?? ''}]`;
    if (msg.animation) return ' [动图]';
    if (msg.video_note) return ' [视频留言]';
    if (msg.contact) return ' [联系人]';
    if (msg.location) return ' [位置]';
    return '';
  }
}

export function makeRelay(env: Env, store: Store, tg: Telegram): RelayTarget {
  // group mode reserved but not enabled in v1.
  return new PrivateRelay(env, store, tg);
}
