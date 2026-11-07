import logging
import os
import json
import time
import hmac
import hashlib
import asyncio
import re
import urllib.request
from urllib.parse import urlencode
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo, InputMediaPhoto, LabeledPrice, ForceReply, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, PreCheckoutQueryHandler, MessageHandler, filters

logging.basicConfig(level=logging.INFO)
# Avoid logging Telegram Bot API URLs containing the secret bot token.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
URL = os.getenv("WEB_APP_URL", "https://wave-web-production.up.railway.app")
TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_URL = os.getenv('WAVE_API_URL', 'https://wave-api-production-c0c4.up.railway.app').rstrip('/')
ADMIN_ID = int(os.getenv("PAYMENT_ADMIN_ID", "0") or 0)
PAYMENT_INSTRUCTIONS = os.getenv("PAYMENT_INSTRUCTIONS", "").strip()
PREVIEW_PHOTOS = [u.strip() for u in os.getenv("PREVIEW_PHOTO_URLS", "").split(",") if u.strip().startswith("https://")][:4]
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Set it in Railway service variables.")

def internal_notifications(path, payload=None, signature_message=None):
    if payload is None:
        body = signature_message or b''
        request = urllib.request.Request(
            API_URL + path,
            headers={"X-Wave-Signature": hmac.new(TOKEN.encode(), body, hashlib.sha256).hexdigest()},
        )
    else:
        body = json.dumps(payload, separators=(',', ':')).encode()
        request = urllib.request.Request(
            API_URL + path, data=body, method="POST",
            headers={"X-Wave-Signature": hmac.new(TOKEN.encode(), body, hashlib.sha256).hexdigest(),
                     "Content-Type": "application/json"},
        )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)

async def register_subscriber(user_id: int):
    try:
        await asyncio.to_thread(internal_notifications, "/api/internal/subscribe", {"user_id": user_id})
    except Exception:
        logging.exception("Subscriber registration failed")

async def reminder_loop(application: Application):
    while True:
        try:
            due = await asyncio.to_thread(internal_notifications, "/api/internal/premium-due", None, b'premium-due')
            for item in due.get('due', []):
                user_id = int(item['user_id'])
                expires_at = int(item['expires_at'])
                claim = await asyncio.to_thread(internal_notifications, "/api/internal/reminder-claim",
                                                {"user_id": user_id, "expires_at": expires_at})
                if not claim.get("claimed"):
                    continue
                date = datetime.fromtimestamp(expires_at, timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
                try:
                    await application.bot.send_message(
                        user_id,
                        f"⏰ WAVE Premium заканчивается менее чем через 24 часа.\n"
                        f"Срок действия: {date}.\n\n"
                        "Продлить подписку можно через /premium. Отключить напоминания: /notifications.",
                    )
                except Exception:
                    logging.exception("Premium reminder delivery failed for user %s", user_id)
                await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Premium reminder check failed")
        await asyncio.sleep(3600)

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("Команда доступна только администратору.")
        return
    content = " ".join(context.args).strip()
    if not content or len(content) > 1000:
        await update.effective_message.reply_text("Использование: /news Текст новости (до 1000 символов).")
        return
    try:
        recipients = await asyncio.to_thread(
            internal_notifications, "/api/internal/notification-recipients?kind=news", None, b"recipients:news"
        )
    except Exception:
        logging.exception("News recipients unavailable")
        await update.effective_message.reply_text("❌ Не удалось получить список подписчиков.")
        return
    sent = 0
    failed = 0
    for user_id in recipients.get("users", []):
        try:
            await context.bot.send_message(
                int(user_id), "📢 Новости WAVE Music\n\n" + content +
                "\n\nОтключить новости: /notifications"
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.07)
    await update.effective_message.reply_text(f"📢 Рассылка завершена. Доставлено: {sent}. Ошибок: {failed}.")

def preview_api(method='GET', photos=None):
    body = json.dumps({'photos': photos}, separators=(',', ':')).encode() if photos is not None else b'preview-read'
    signature = hmac.new(TOKEN.encode(), body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(API_URL + '/api/internal/previews',
        data=body if method == 'POST' else None,
        headers={'X-Wave-Signature': signature, 'Content-Type': 'application/json'}, method=method)
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎧 Открыть WAVE Music", web_app=WebAppInfo(url=URL))],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton("💎 Подписка Premium", callback_data="premium_info")],
        [InlineKeyboardButton("ℹ️ О WAVE Music", callback_data="about"), InlineKeyboardButton("❓ Помощь", callback_data="help_info")],
        [InlineKeyboardButton("💬 Поддержка", callback_data="support_start")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await register_subscriber(update.effective_user.id)
    try:
        saved = await asyncio.to_thread(preview_api)
        photos = saved.get('photos') or PREVIEW_PHOTOS
    except Exception:
        logging.exception('Could not load previews')
        photos = PREVIEW_PHOTOS
    if photos:
        try:
            if len(photos) == 1:
                await update.effective_message.reply_photo(photos[0], caption="📱 Интерфейс WAVE Music")
            else:
                await update.effective_message.reply_media_group(
                    [InputMediaPhoto(media=u, caption="📱 Интерфейс WAVE Music" if i == 0 else None) for i, u in enumerate(photos)]
                )
        except Exception:
            logging.exception("Unable to send preview screenshots")

    await update.effective_message.reply_text(
        "🌊 Добро пожаловать в WAVE Music! 🎧\n\n"
        "🎶 Твоя музыка. Твой ритм. Твоя волна.\n\n"
        "👥 Создавай музыкальные комнаты, приглашай друзей и слушайте музыку вместе.\n"
        "🎛 Назначай DJ и управляй очередью треков.\n\n"
        "Нажми кнопку, чтобы открыть приложение прямо в Telegram.",
        reply_markup=main_keyboard(),
    )

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

async def setpreview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info('setpreview received user_id=%s admin_configured=%s reply_photo=%s', update.effective_user.id, bool(ADMIN_ID), bool(update.effective_message.reply_to_message and update.effective_message.reply_to_message.photo))
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text('Настройка доступна только администратору.')
        return
    photo = update.effective_message.reply_to_message
    if not photo or not photo.photo:
        await update.effective_message.reply_text('Ответь командой /setpreview на фотографию в этом чате.')
        return
    try:
        old = await asyncio.to_thread(preview_api)
        photos = (old.get('photos', []) + [photo.photo[-1].file_id])[-4:]
        await asyncio.to_thread(preview_api, 'POST', photos)
        await update.effective_message.reply_text(f'✅ Фото сохранено ({len(photos)}/4). Оно появится после /start.')
    except Exception:
        logging.exception('Failed to save preview')
        await update.effective_message.reply_text('Не удалось сохранить фото. Попробуй позже.')

async def preview_command_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message and message.text and message.text.strip().split()[0].split('@')[0].lower() == '/setpreview':
        await setpreview(update, context)

async def clearpreviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        return
    try:
        await asyncio.to_thread(preview_api, 'POST', [])
        await update.effective_message.reply_text('Фотографии приветствия очищены.')
    except Exception:
        logging.exception('Failed to clear previews')

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID:
        await update.effective_message.reply_text("Поддержка временно недоступна. Попробуй позже.")
        return
    context.user_data["support_mode"] = True
    await update.effective_message.reply_text(
        "💬 Поддержка WAVE Music\n\nОпиши проблему одним текстовым сообщением (до 3000 символов). "
        "Не отправляй пароли, коды входа или данные банковской карты.\n\n"
        "Для отмены отправь /cancel.",
        reply_markup=ForceReply(selective=True, input_field_placeholder="Опиши проблему для поддержки…"),
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("support_mode", None)
    await update.effective_message.reply_text("Обращение отменено.", reply_markup=ReplyKeyboardRemove())
    await update.effective_message.reply_text("🌊 Главное меню", reply_markup=main_keyboard())

async def support_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    if not message or not message.text or not user:
        return
    if user.id == ADMIN_ID and message.reply_to_message:
        original = message.reply_to_message.text or ""
        match = re.match(r"^🎫 WAVE SUPPORT\nUser ID: (\d+)\n", original)
        if match:
            target = int(match.group(1))
            if target == ADMIN_ID:
                await message.reply_text("🧪 Тестовый ответ обработан. Это твой администраторский чат, поэтому пересылка самому себе не требуется.")
                return
            try:
                await context.bot.send_message(
                    chat_id=target,
                    text="💬 Ответ поддержки WAVE Music:\n\n" + message.text[:3500],
                )
                await message.reply_text("✅ Ответ доставлен пользователю.")
            except Exception:
                logging.exception("Support response delivery failed")
                await message.reply_text("❌ Не удалось доставить ответ. Возможно, пользователь заблокировал бота.")
            return
    if not context.user_data.get("support_mode"):
        return
    # Only accept the response to the support prompt; other chat messages stay outside the ticket flow.
    prompt = message.reply_to_message
    if not prompt or not prompt.from_user or prompt.from_user.id != context.bot.id or not (prompt.text or "").startswith("💬 Поддержка WAVE Music"):
        await message.reply_text("Чтобы отправить обращение, ответь на сообщение «💬 Поддержка WAVE Music» или начни заново через /support.")
        return
    if not 1 <= len(message.text.strip()) <= 3000:
        await message.reply_text("Напиши сообщение длиной от 1 до 3000 символов.")
        return
    last = context.user_data.get("support_last_sent", 0)
    if time.time() - last < 60:
        await message.reply_text("Следующее обращение можно отправить через минуту.")
        return
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🎫 WAVE SUPPORT\nUser ID: {user.id}\n\n"
                 f"Сообщение пользователя:\n{message.text.strip()}"
                 + ("\n\n🧪 Тестовая заявка администратора" if user.id == ADMIN_ID else ""),
        )
        context.user_data["support_last_sent"] = time.time()
        context.user_data.pop("support_mode", None)
        await message.reply_text(
            "🧪 Тестовая заявка доставлена в этот чат. Ответь на сообщение «🎫 WAVE SUPPORT», чтобы проверить обработку ответа."
            if user.id == ADMIN_ID else
            "✅ Обращение отправлено! Администратор ответит здесь, в этом чате.",
            reply_markup=main_keyboard(),
        )
    except Exception:
        logging.exception("Support ticket delivery failed")
        await message.reply_text("❌ Не удалось отправить обращение. Попробуй позже.")

def premium_status_api(user_id: int):
    signature = hmac.new(TOKEN.encode(), f"premium-read:{user_id}".encode(), hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        API_URL + "/api/internal/premium?" + urlencode({"user_id": user_id}),
        headers={"X-Wave-Signature": signature},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)

def notification_api(user_id: int, key=None, enabled=None):
    if key is None:
        signature = hmac.new(TOKEN.encode(), f"notifications-read:{user_id}".encode(), hashlib.sha256).hexdigest()
        request = urllib.request.Request(
            API_URL + "/api/internal/notifications?" + urlencode({"user_id": user_id}),
            headers={"X-Wave-Signature": signature},
        )
    else:
        body = json.dumps({"user_id": user_id, "key": key, "enabled": enabled}, separators=(",", ":")).encode()
        signature = hmac.new(TOKEN.encode(), body, hashlib.sha256).hexdigest()
        request = urllib.request.Request(
            API_URL + "/api/internal/notifications", data=body,
            headers={"X-Wave-Signature": signature, "Content-Type": "application/json"}, method="POST",
        )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)

def profile_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Настройки уведомлений", callback_data="notification_settings")],
        [InlineKeyboardButton("💎 Premium", callback_data="premium_info")],
        [InlineKeyboardButton("🎧 Открыть приложение", web_app=WebAppInfo(url=URL))],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
    ])

async def notifications_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await register_subscriber(user.id)
    try:
        settings = await asyncio.to_thread(notification_api, user.id)
    except Exception:
        logging.exception("Notification settings unavailable")
        await update.effective_message.reply_text("⚠️ Настройки временно недоступны. Попробуй позже.")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(("✅" if settings.get("news", True) else "❌") + " Новости WAVE", callback_data="notify_news")],
        [InlineKeyboardButton(("✅" if settings.get("premium", True) else "❌") + " Напоминания Premium", callback_data="notify_premium")],
        [InlineKeyboardButton("👤 Вернуться в профиль", callback_data="profile")],
    ])
    await update.effective_message.reply_text(
        "🔔 Настройки уведомлений\n\nВыбери, какие уведомления разрешить. "
        "Настройки сохраняются в твоём аккаунте. Напоминания Premium отправляются автоматически, новости — администратором.",
        reply_markup=keyboard,
    )

async def notifications_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.removeprefix("notify_")
    try:
        settings = await asyncio.to_thread(notification_api, query.from_user.id)
        await asyncio.to_thread(notification_api, query.from_user.id, key, not bool(settings.get(key, True)))
        await query.message.reply_text("✅ Настройка сохранена.")
        await notifications_command(update, context)
    except Exception:
        logging.exception("Notification preference update failed")
        await query.message.reply_text("❌ Не удалось сохранить настройку. Попробуй позже.")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    name = user.full_name or "Пользователь"
    try:
        premium = await asyncio.to_thread(premium_status_api, user.id)
        expires = int(premium.get("expires_at") or 0)
        active = bool(premium.get("active"))
        if active:
            end_date = datetime.fromtimestamp(expires, timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
            status = f"💎 Premium активен до {end_date}"
        else:
            status = "🎵 Бесплатный аккаунт"
    except Exception:
        logging.exception("Profile Premium status unavailable")
        status = "⚠️ Не удалось проверить Premium. Попробуй позже."
    await update.effective_message.reply_text(
        f"👤 Профиль WAVE Music\n\n"
        f"Имя: {name}\n"
        f"Telegram ID: {user.id}\n"
        f"Статус: {status}\n\n"
        "Управление музыкой и комнатами доступно в приложении.",
        reply_markup=profile_keyboard(),
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        '❓ Помощь WAVE Music\n\n'
        '/start — приветствие и запуск приложения\n'
        '/about — информация о сервисе\n'
        '/premium — оформить Premium за 159 ⭐ на 30 дней\n'
        '/profile — профиль и статус подписки\n'
        '/notifications — настройки уведомлений\n'
        '/support — написать в поддержку\n'
        '/cancel — отменить обращение\n'
        '/help — список команд\n\n'
        'Если музыка не запускается, проверь подключение и доступность аудиоисточника.',
        reply_markup=main_keyboard())

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        '🌊 WAVE Music — музыкальное приложение внутри Telegram.\n\n'
        '🎵 Поиск треков и личная медиатека\n'
        '👥 Совместные музыкальные комнаты\n'
        '🎛 Управление очередью для владельца и DJ\n\n'
        'Некоторые возможности, включая воспроизведение внешнего каталога, ещё разрабатываются.',
        reply_markup=main_keyboard())

async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        '💎 WAVE Premium — 159 ⭐ за 30 дней.\n'
        'Нажми «Подписка Premium», чтобы открыть счёт Telegram Stars.\n'
        'Покупка не продлевается автоматически.', reply_markup=main_keyboard())

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    if query.data=='about':
        await about_command(update, context)
    elif query.data=='help_info':
        await help_command(update, context)
    elif query.data=='support_start':
        await support_command(update, context)
    elif query.data=='profile':
        await profile_command(update, context)
    elif query.data=='notification_settings':
        await notifications_command(update, context)
    elif query.data=='main_menu':
        await query.message.reply_text('🌊 Главное меню WAVE Music', reply_markup=main_keyboard())

async def post_init(application: Application):
    application.bot_data['reminder_task'] = asyncio.create_task(reminder_loop(application))
    await application.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="🎧 WAVE Music", web_app=WebAppInfo(url=URL)))

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("notifications", notifications_command))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("support", support_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("setpreview", setpreview))
    app.add_handler(CommandHandler("clearpreviews", clearpreviews))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, support_messages))
    app.add_handler(CallbackQueryHandler(premium_info, pattern="^premium_info$"))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^(about|help_info|support_start|profile|notification_settings|main_menu)$"))
    app.add_handler(CallbackQueryHandler(notifications_callback, pattern="^notify_(news|premium)$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
