import logging
import os
import json
import time
import hmac
import hashlib
import asyncio
import urllib.request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo, InputMediaPhoto, LabeledPrice
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, PreCheckoutQueryHandler, MessageHandler, filters

logging.basicConfig(level=logging.INFO)
URL = os.getenv("WEB_APP_URL", "https://wave-web-production.up.railway.app")
TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_URL = os.getenv('WAVE_API_URL', 'https://wave-api-production-c0c4.up.railway.app').rstrip('/')
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
    await query.message.reply_invoice(
        title="WAVE Premium — 30 дней",
        description="30 дней Premium-доступа WAVE Music. Подписка продлевается только после новой оплаты.",
        payload=f"wave_premium_30:{query.from_user.id}",
        currency="XTR",
        prices=[LabeledPrice(label="WAVE Premium — 30 дней", amount=159)],
        provider_token="",
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    valid = (query.currency == "XTR" and query.total_amount == 159
             and query.invoice_payload == f"wave_premium_30:{query.from_user.id}")
    await query.answer(ok=valid, error_message=None if valid else "Параметры платежа не совпадают.")

def save_stars_payment(user_id: int, charge_id: str):
    payload = json.dumps({"user_id": user_id, "charge_id": charge_id, "stars": 159,
                          "paid_at": int(time.time())}, separators=(",", ":")).encode()
    signature = hmac.new(TOKEN.encode(), payload, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        API_URL + "/api/internal/stars", data=payload,
        headers={"Content-Type": "application/json", "X-Wave-Signature": signature},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.effective_message.successful_payment
    if not payment or payment.currency != "XTR" or payment.total_amount != 159:
        return
    if payment.invoice_payload != f"wave_premium_30:{update.effective_user.id}":
        logging.error("Unexpected Stars payment payload")
        return
    try:
        result = await asyncio.to_thread(
            save_stars_payment, update.effective_user.id, payment.telegram_payment_charge_id
        )
        if not result.get("ok"):
            raise RuntimeError("API did not confirm payment")
        await update.effective_message.reply_text(
            "✅ Оплата 159 ⭐ получена! Premium активирован на 30 дней. "
            "Открой WAVE Music, чтобы продолжить.", reply_markup=main_keyboard()
        )
    except Exception:
        logging.exception("Payment recorded by Telegram but Premium activation failed")
        await update.effective_message.reply_text(
            "⭐ Telegram подтвердил оплату, но активация пока не завершилась. "
            "Обратись в поддержку с идентификатором платежа: " +
            payment.telegram_payment_charge_id
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Нажми /start, чтобы открыть WAVE Music или узнать о Premium.")

async def post_init(application: Application):
    await application.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="🎧 WAVE Music", web_app=WebAppInfo(url=URL)))

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(premium_info, pattern="^premium_info$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
