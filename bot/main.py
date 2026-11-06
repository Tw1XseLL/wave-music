import asyncio
import logging
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
URL = os.getenv("WEB_APP_URL", "https://wave-web-production.up.railway.app")
TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Set it in Railway service variables.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🎧 Открыть WAVE Music", web_app=WebAppInfo(url=URL))]])
    await update.effective_message.reply_text(
        "🌊 Добро пожаловать в WAVE Music!\n\nТвоя музыка — в одном месте. Нажми кнопку, чтобы открыть приложение прямо в Telegram.",
        reply_markup=keyboard,
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Отправь /start и нажми «Открыть WAVE Music». 🎶")

async def post_init(application: Application):
    await application.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="🎧 WAVE Music", web_app=WebAppInfo(url=URL)))

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
