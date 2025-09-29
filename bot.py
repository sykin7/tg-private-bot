from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os

# 你的 Telegram 用户 ID（替换为实际 ID）
OWNER_ID = 5768851426  # 例如 123456789

async def start(update, context):
    await update.message.reply_text('欢迎！我是你的专属私聊机器人。你的消息会转发给主人。')

async def forward_message(update, context):
    user = update.message。from_user
    message = update.message.text 或 "非文本消息"  # 注意: 用英文 'or'
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"来自 {user.first_name} (ID: {user.id}): {message}"
    )
    await update.message。reply_text('消息已转发给主人！')

def main():
    token = os.getenv('BOT_TOKEN')
    app = Application.builder()。token(token).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_message))
    app.run_polling()

if __name__ == '__main__':
    main()
