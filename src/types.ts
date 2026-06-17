export interface Env {
  // Bindings
  TG_BOT_KV: KVNamespace;
  AI: Ai;

  // Secrets (set via `wrangler secret put`)
  BOT_TOKEN: string;
  BOT_SECRET: string;
  AI_API_KEY: string;
  SEARCH_API_KEY: string;
  // SECURITY FIX (C1): ADMIN_UID and AI_BASE_URL moved from Vars to Secrets
  // to prevent leaking admin identity and relay station URL in public forks.
  ADMIN_UID: string;
  AI_BASE_URL: string;

  // Vars (non-sensitive config)
  BOT_USERNAME: string;
  RELAY_MODE: string;
  ADMIN_GROUP_ID: string;

  AI_MODEL: string;
  AI_TIMEOUT_MS: string;
  // FIX B7: separate timeout for classification (should be fast)
  AI_CLASSIFY_TIMEOUT_MS: string;
  AI_PROVIDER: string;
  AI_FALLBACK_TO_CF: string;
  CF_AI_MODEL: string;

  FILTER_ENABLED: string;
  FILTER_THRESHOLD: string;
  BLOCK_KEYWORDS: string;

  VERIFY_MODE: string;
  VERIFY_QUESTION: string;
  VERIFY_ANSWER: string;

  WELCOME_MESSAGE: string;
  AUTO_GREETING: string;
  AI_REPLY_PREVIEW: string;
  AI_CONTEXT_ROUNDS: string;

  AUTO_BAN_THRESHOLD: string;
  BAN_MESSAGE: string;
  APPEAL_MAX_ATTEMPTS: string;
  APPEAL_MESSAGE: string;

  AUTO_SEARCH_ENABLED: string;
  SEARCH_PROVIDER: string;
  SEARCH_MAX_RESULTS: string;
  SEARCH_DECISION_MODEL: string;

  GROUP_AI_ENABLED: string;
  GROUP_AI_MAX_CONCURRENCY: string;
  GROUP_AI_LOCK_TTL_SECONDS: string;
  GROUP_USER_COOLDOWN_SECONDS: string;
  GROUP_AI_CONTEXT_ROUNDS: string;
  GROUP_AI_MAX_INPUT_CHARS: string;
  GROUP_AI_MAX_OUTPUT_CHARS: string;

  // Dev / debug
  BYPASS_TG_ASN_CHECK: string;
  // FIX B21: optional override for webhook URL (useful for local dev / tunnels)
  WEBHOOK_URL_OVERRIDE: string;
}

export type SpamCategory = 'normal' | 'ad' | 'scam' | 'spam';

export interface Classification {
  category: SpamCategory;
  confidence: number;
  reason: string;
  provider: 'relay' | 'workers_ai' | 'keyword' | 'none';
}

export interface UserProfile {
  id: number;
  name?: string;
  username?: string;
  verified: boolean;
  greeted: boolean;
  createdAt: number;
  lastSeenAt: number;
}

export interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
}

// Minimal Telegram update typing (only what we use).
export interface TgUser {
  id: number;
  is_bot: boolean;
  first_name?: string;
  last_name?: string;
  username?: string;
}

export interface TgChat {
  id: number;
  type: string;
}

export interface TgMessageEntity {
  type: string;
  offset: number;
  length: number;
}

// SECURITY FIX (H4): Added media fields so non-text messages can be detected
// and routed through the AI filter.
export interface TgMessage {
  message_id: number;
  from?: TgUser;
  chat: TgChat;
  date?: number;
  edit_date?: number;
  text?: string;
  caption?: string;
  entities?: TgMessageEntity[];
  caption_entities?: TgMessageEntity[];
  reply_to_message?: TgMessage;
  forward_origin?: unknown;
  // Media types
  photo?: { file_id: string; file_unique_id: string; file_size: number; width: number; height: number }[];
  document?: { file_id: string; file_unique_id: string; file_name?: string; mime_type?: string; file_size?: number };
  video?: { file_id: string; file_unique_id: string; file_size?: number; duration?: number; width?: number; height?: number };
  voice?: { file_id: string; file_unique_id: string; file_size?: number; duration: number };
  audio?: { file_id: string; file_unique_id: string; file_size?: number; duration?: number; title?: string };
  sticker?: { file_id: string; file_unique_id: string; emoji?: string; is_animated?: boolean; is_video?: boolean };
  animation?: { file_id: string; file_unique_id: string; file_size?: number };
  video_note?: { file_id: string; file_unique_id: string; length: number; duration: number };
  contact?: { phone_number: string; first_name: string; last_name?: string; user_id?: number };
  location?: { longitude: number; latitude: number };
  dice?: { emoji: string; value: number };
  media_group_id?: string;
}

export interface TgUpdate {
  update_id: number;
  message?: TgMessage;
  edited_message?: TgMessage;
  callback_query?: {
    id: string;
    from: TgUser;
    data?: string;
    message?: TgMessage;
  };
}

// Audit log entry (SECURITY FIX M1)
export interface AuditLogEntry {
  time: number;
  actor: number;
  action: string;
  target: string;
  detail: string;
}
