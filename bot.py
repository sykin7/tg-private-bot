from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os

async def start(update, context):
    await update.message.reply_text('欢迎！我是你的私聊机器人。')

async def echo(update, context):
    await update.message.reply_text(f'你说：{update.message.text}')

def main():
    token = os.getenv('BOT_TOKEN')  # 从 ClawCloud 环境变量读 token
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    app.run_polling()

if __name__ == '__main__':
    main()
