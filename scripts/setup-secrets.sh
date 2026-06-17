#!/usr/bin/env bash
# Helper script to set up all Cloudflare Worker secrets interactively.
# Run after `npm install` and before `npm run deploy`.
set -euo pipefail

if ! command -v wrangler >/dev/null 2>&1; then
  echo "wrangler not found. Run 'npm install' first."
  exit 1
fi

echo "=== nicechat-bot secret setup ==="
echo "This will prompt you for each secret. Press Ctrl+C to cancel."
echo

read -r -p "BOT_TOKEN (from @BotFather): " BOT_TOKEN
[ -z "$BOT_TOKEN" ] && echo "BOT_TOKEN is required" && exit 1

read -r -p "BOT_SECRET (random long string for webhook auth): " BOT_SECRET
[ -z "$BOT_SECRET" ] && echo "BOT_SECRET is required" && exit 1

read -r -p "ADMIN_UID (your Telegram user ID): " ADMIN_UID
[ -z "$ADMIN_UID" ] && echo "ADMIN_UID is required" && exit 1

read -r -p "AI_BASE_URL (OpenAI-compatible relay URL, no /chat/completions): " AI_BASE_URL
[ -z "$AI_BASE_URL" ] && echo "AI_BASE_URL is required" && exit 1

read -r -p "AI_API_KEY (relay station API key): " AI_API_KEY
[ -z "$AI_API_KEY" ] && echo "AI_API_KEY is required" && exit 1

read -r -p "SEARCH_API_KEY (optional, leave blank to skip): " SEARCH_API_KEY

echo
echo "Setting secrets via wrangler..."
echo "$BOT_TOKEN"    | wrangler secret put BOT_TOKEN
echo "$BOT_SECRET"   | wrangler secret put BOT_SECRET
echo "$ADMIN_UID"    | wrangler secret put ADMIN_UID
echo "$AI_BASE_URL"  | wrangler secret put AI_BASE_URL
echo "$AI_API_KEY"   | wrangler secret put AI_API_KEY
[ -n "$SEARCH_API_KEY" ] && echo "$SEARCH_API_KEY" | wrangler secret put SEARCH_API_KEY

echo
echo "✅ All secrets set. Next steps:"
echo "  1. Create KV namespace:    npm run kv:create"
echo "  2. Update wrangler.jsonc with the KV id"
echo "  3. Deploy:                 npm run deploy"
echo "  4. Register webhook (POST + header):"
echo "     curl -X POST -H \"x-bot-secret: \$BOT_SECRET\" https://<your-worker>.workers.dev/registerWebhook"
echo "  5. Set commands (POST + header):"
echo "     curl -X POST -H \"x-bot-secret: \$BOT_SECRET\" https://<your-worker>.workers.dev/setcommands"
