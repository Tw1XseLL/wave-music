import logging
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
URL = os.getenv("WEB_APP_URL", "https://wave-web-production.up.railway.app")
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("PAYMENT_ADMIN_ID", "0") or 0)
PAYMENT_INSTRUCTIONS = os.getenv("PAYMENT_INSTRUCTIONS", "").strip()
PREVIEW_PHOTOS = [u.strip() for u in os.getenv("PREVIEW_PHOTO_URLS", "").split(",") if u.strip().startswith("https://")][:4]
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Set it in Railway service variables.")

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎧 Открыть WAVE Music", web_app=WebAppInfo(url=URL))],
        [InlineKeyboardButton("💎 Подписка Premium", callback_data="premium_info")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🌊 Добро пожаловать в WAVE Music! 🎧\n\n"
        "🎶 Твоя музыка. Твой ритм. Твоя волна.\n\n"
        "👥 Создавай музыкальные комнаты, приглашай друзей и слушайте музыку вместе.\n"
        "🎛 Назначай DJ и управляй очередью треков.\n\n"
        "Нажми кнопку, чтобы открыть приложение прямо в Telegram.",
        reply_markup=main_keyboard(),
    )
    if PREVIEW_PHOTOS:
        try:
            if len(PREVIEW_PHOTOS) == 1:
                await update.effective_message.reply_photo(PREVIEW_PHOTOS[0], caption="📱 Интерфейс WAVE Music")
            else:
                await update.effective_message.reply_media_group(
                    [InputMediaPhoto(media=u, caption="📱 Интерфейс WAVE Music" if i == 0 else None) for i, u in enumerate(PREVIEW_PHOTOS)]
                )
        except Exception:
            logging.exception("Unable to send preview screenshots")

async def premium_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not ADMIN_ID or not PAYMENT_INSTRUCTIONS:
        await query.message.reply_text("💎 Premium готовится к запуску. Приём платежей пока не открыт.")
        return
    await query.message.reply_text(
        "💎 WAVE Premium\n\n" + PAYMENT_INSTRUCTIONS +
        "\n\nОплата проверяется вручную. Не отправляй данные банковской карты или пароли. "
        "После оплаты нажми «Я оплатил», чтобы связаться с администратором.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📨 Я оплатил", callback_data="payment_request")]])
    )

async def payment_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not ADMIN_ID or not PAYMENT_INSTRUCTIONS:
        await query.message.reply_text("Приём платежей пока не открыт.")
        return
    user = query.from_user
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"💎 Запрос на проверку оплаты WAVE Music\nUser ID: {user.id}\nUsername: @{user.username or 'нет'}\n"
             "Проверь фактическое поступление денег независимо от сообщений пользователя. "
             "Подписка автоматически не активируется."
    )
    await query.message.reply_text("📨 Запрос отправлен администратору. Сохрани подтверждение платежа. "
                                   "Premium пока не активирован — дождись проверки.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Нажми /start, чтобы открыть WAVE Music или узнать о Premium.")

async def post_init(application: Application):
    await application.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="🎧 WAVE Music", web_app=WebAppInfo(url=URL)))

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(premium_info, pattern="^premium_info$"))
    app.add_handler(CallbackQueryHandler(payment_request, pattern="^payment_request$"))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
