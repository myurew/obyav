import os
import re
import logging
import html
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters, JobQueue
)
import sqlite3
import pytz

# === НАСТРОЙКИ ===
BOT_TOKEN = "TOKEN"
GROUP_CHAT_ID = ID  # ID канала @poputchik_asino

TZ = pytz.timezone('Asia/Novosibirsk')

(
    SELECT_ROLE,
    SELECT_ROUTE,
    FROM_LOCATION,
    TO_LOCATION,
    SELECT_DATE,
    SELECT_TIME,
    MANUAL_TIME_INPUT,
    PRICE,
    SEATS,
    COMMENT,
    CONTACT_METHOD,
    CONTACT_PHONE
) = range(12)

def init_db():
    conn = sqlite3.connect('rides.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS rides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            from_loc TEXT,
            to_loc TEXT,
            date TEXT,
            time_slot TEXT,
            seats INTEGER,
            comment TEXT,
            contact TEXT,
            username TEXT,
            message_id INTEGER,
            price TEXT
        )
    ''')
    conn.commit()
    return conn

DB_CONN = init_db()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def escape_html(text: str) -> str:
    return html.escape(str(text))

def clean_phone(phone: str) -> str:
    digits = re.sub(r'\D', '', phone)
    if len(digits) not in (10, 11):
        raise ValueError("Номер должен содержать 10 или 11 цифр")
    return digits

def format_phone(phone: str) -> str:
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 11 and digits[0] in ('7', '8'):
        digits = digits[1:]
    if len(digits) == 10:
        return f"8 {digits[:3]} {digits[3:6]} {digits[6:8]} {digits[8:]}"
    return f"8 {digits}"

def get_date_slots():
    today = datetime.now(TZ).date()
    buttons = []
    for i in range(7):
        d = today + timedelta(days=i)
        buttons.append(InlineKeyboardButton(d.strftime("%d.%m"), callback_data=f"date_{d.isoformat()}"))
    return [buttons[:4], buttons[4:]]

def get_time_slots(selected_date):
    now = datetime.now(TZ)
    today = now.date()
    is_today = (selected_date == today)
    slots = []

    for h in range(6, 24):
        slot_start = f"{h:02d}:00"
        next_h = (h + 1) % 24
        slot_end = f"{next_h:02d}:00"
        slot_label = f"{slot_start} - {slot_end}"

        if is_today:
            slot_time = datetime.strptime(slot_start, "%H:%M").time()
            if now.time() >= slot_time:
                continue
        slots.append(InlineKeyboardButton(slot_label, callback_data=f"time_{slot_start}_{slot_end}"))

    # Формируем ряды по 2 кнопки из временных слотов
    rows = []
    for i in range(0, len(slots), 2):
        rows.append(slots[i:i+2])
    
    # Добавляем "Указать время вручную" ОТДЕЛЬНОЙ СТРОКОЙ ВНИЗУ
    rows.append([InlineKeyboardButton("✏️ Указать время вручную", callback_data="time_manual")])
    
    return rows

def get_price_slots():
    prices = [480, 450, 420]
    buttons = [
        [InlineKeyboardButton("По цене билета", callback_data="price_text_По цене билета")],
        [InlineKeyboardButton(f"{p} ₽", callback_data=f"price_{p}") for p in prices]
    ]
    buttons.append([InlineKeyboardButton("✏️ Указать вручную", callback_data="price_manual")])
    return buttons

def get_deletion_time(ride_data):
    """
    Всегда возвращает datetime. Никогда не вызывает исключение.
    - Для стандартных слотов: удаляем после поездки + 2 часа
    - Для всего остального: через 48 часов
    """
    try:
        time_slot = ride_data['time']
        
        if " - " in time_slot:
            parts = time_slot.split(" - ")
            if len(parts) == 2:
                start_parts = parts[0].split(":")
                end_parts = parts[1].split(":")
                if len(start_parts) == 2 and len(end_parts) == 2:
                    start_h = int(start_parts[0])
                    start_m = int(start_parts[1])
                    end_h = int(end_parts[0])
                    end_m = int(end_parts[1])
                    
                    if 0 <= start_h <= 23 and 0 <= end_h <= 23 and start_m == 0 and end_m == 0:
                        date_part = datetime.fromisoformat(ride_data['date']).date()
                        is_hourly = (end_h - start_h == 1) or (start_h == 23 and end_h == 0)

                        if is_hourly:
                            deletion_hour = start_h + 2
                            deletion_minute = 0
                            deletion_date = date_part
                        else:
                            deletion_hour = end_h + 1
                            deletion_minute = 0
                            if deletion_hour >= 24:
                                deletion_hour = 0
                                deletion_date = date_part + timedelta(days=1)
                            else:
                                deletion_date = date_part

                        dt = datetime.combine(deletion_date, datetime.min.time().replace(hour=deletion_hour, minute=deletion_minute))
                        return TZ.localize(dt)
    except Exception:
        pass  # Любая ошибка → fallback на 48 часов

    return datetime.now(TZ) + timedelta(hours=48)

# === ОБРАБОТЧИКИ ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🚗 Я водитель", callback_data="role_driver")],
        [InlineKeyboardButton("👤 Я пассажир", callback_data="role_passenger")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Все поездки публикуются в канале: @poputchik_asino\n\n"
        "Как создать поездку: нажмите МЕНЮ - Инструкция или /info\n\n"
        "Вы водитель или пассажир?",
        reply_markup=reply_markup
    )
    return SELECT_ROLE

async def role_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    role = query.data.split("_")[1]
    context.user_data['ride'] = {'role': role}

    keyboard = [
        [
            InlineKeyboardButton("  Асино — Томск  ", callback_data="route_asino_tomsk"),
            InlineKeyboardButton("  Томск — Асино  ", callback_data="route_tomsk_asino")
        ],
        [
            InlineKeyboardButton("✏️ Указать вручную", callback_data="route_manual")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("📍 Выберите маршрут:", reply_markup=reply_markup)
    return SELECT_ROUTE

async def route_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "route_asino_tomsk":
        context.user_data['ride']['from'] = "Асино"
        context.user_data['ride']['to'] = "Томск"
        reply_markup = InlineKeyboardMarkup(get_date_slots())
        await query.edit_message_text("📅 Выберите дату поездки:", reply_markup=reply_markup)
        return SELECT_DATE

    elif data == "route_tomsk_asino":
        context.user_data['ride']['from'] = "Томск"
        context.user_data['ride']['to'] = "Асино"
        reply_markup = InlineKeyboardMarkup(get_date_slots())
        await query.edit_message_text("📅 Выберите дату поездки:", reply_markup=reply_markup)
        return SELECT_DATE

    elif data == "route_manual":
        await query.edit_message_text("📍 Откуда выезжаете / откуда вам нужно уехать?")
        return FROM_LOCATION

    else:
        await query.edit_message_text("❌ Неизвестный маршрут. Начните заново: /start")
        return ConversationHandler.END

async def from_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ride']['from'] = update.message.text.strip()
    await update.message.reply_text("📍 Куда едете / куда вам нужно попасть?")
    return TO_LOCATION

async def to_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ride']['to'] = update.message.text.strip()
    reply_markup = InlineKeyboardMarkup(get_date_slots())
    await update.message.reply_text("📅 Выберите дату поездки:", reply_markup=reply_markup)
    return SELECT_DATE

async def date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    date_iso = query.data.split("_", 1)[1]
    context.user_data['ride']['date'] = date_iso

    selected_date = datetime.fromisoformat(date_iso).date()
    reply_markup = InlineKeyboardMarkup(get_time_slots(selected_date))
    await query.edit_message_text("🕗 Выберите время:", reply_markup=reply_markup)
    return SELECT_TIME

async def time_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "time_manual":
        await query.edit_message_text("🕗 Укажите желаемое время:")
        return MANUAL_TIME_INPUT

    elif data.startswith("time_") and len(data.split("_")) == 3:
        parts = data.split("_")
        start_time = parts[1]
        end_time = parts[2]
        context.user_data['ride']['time'] = f"{start_time} - {end_time}"

        role = context.user_data['ride']['role']
        if role == 'driver':
            reply_markup = InlineKeyboardMarkup(get_price_slots())
            await query.edit_message_text("💰 Выберите цену за поездку:", reply_markup=reply_markup)
            return PRICE
        else:
            max_seats = 4
            keyboard = [[InlineKeyboardButton(str(i), callback_data=f"seats_{i}") for i in range(1, max_seats + 1)]]
            await query.edit_message_text(
                "👤 Сколько нужно мест?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SEATS
    else:
        await query.edit_message_text("❌ Неверный выбор времени. Начните заново: /start")
        return ConversationHandler.END

async def manual_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("🕗 Введите хотя бы что-нибудь:")
        return MANUAL_TIME_INPUT

    context.user_data['ride']['time'] = text

    role = context.user_data['ride']['role']
    if role == 'driver':
        reply_markup = InlineKeyboardMarkup(get_price_slots())
        await update.message.reply_text("💰 Выберите цену за поездку:", reply_markup=reply_markup)
        return PRICE
    else:
        max_seats = 4
        keyboard = [[InlineKeyboardButton(str(i), callback_data=f"seats_{i}") for i in range(1, max_seats + 1)]]
        await update.message.reply_text(
            "👤 Сколько нужно мест?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SEATS

async def price_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "price_manual":
        await query.edit_message_text("💰 Введите цену (только цифры):")
        return PRICE

    elif data.startswith("price_text_"):
        price_text = data.split("price_text_", 1)[1]
        context.user_data['ride']['price'] = price_text
        max_seats = 5
        keyboard = [[InlineKeyboardButton(str(i), callback_data=f"seats_{i}") for i in range(1, max_seats + 1)]]
        await query.edit_message_text(
            "👤 Сколько свободных мест?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SEATS

    elif data.startswith("price_"):
        try:
            price = int(data.split("_", 1)[1])
            context.user_data['ride']['price'] = str(price)
            max_seats = 5
            keyboard = [[InlineKeyboardButton(str(i), callback_data=f"seats_{i}") for i in range(1, max_seats + 1)]]
            await query.edit_message_text(
                "👤 Сколько свободных мест?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SEATS
        except ValueError:
            await query.edit_message_text("❌ Неверная цена. Начните заново: /start")
            return ConversationHandler.END
    else:
        await query.edit_message_text("❌ Неизвестный выбор. /start")
        return ConversationHandler.END

async def manual_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Введите только цифры (например: 500)")
        return PRICE

    price = int(text)
    if price <= 0 or price > 5000:
        await update.message.reply_text("❌ Укажите разумную цену (от 1 до 5000)")
        return PRICE

    context.user_data['ride']['price'] = str(price)

    max_seats = 5
    keyboard = [[InlineKeyboardButton(str(i), callback_data=f"seats_{i}") for i in range(1, max_seats + 1)]]
    await update.message.reply_text(
        "👤 Сколько свободных мест?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SEATS

async def seats_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    seats = int(query.data.split("_")[1])
    context.user_data['ride']['seats'] = seats
    
    keyboard = [[InlineKeyboardButton("Пропустить", callback_data="skip_comment")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "💬 Добавьте комментарий (ребёнок, груз, \"могу забрать с адреса\" и т.д.)",
        reply_markup=reply_markup
    )
    return COMMENT

async def comment_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ride']['comment'] = update.message.text.strip()[:200]
    await show_contact_options(update, context)
    return CONTACT_METHOD

async def skip_comment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['ride']['comment'] = ""
    await show_contact_options(query, context)
    return CONTACT_METHOD

async def show_contact_options(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📱 Указать номер", callback_data="contact_phone")],
        [InlineKeyboardButton("💬 Принимать в ЛС", callback_data="contact_pm")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text("Как связаться с вами?", reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text("Как связаться с вами?", reply_markup=reply_markup)

async def contact_method_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.split("_")[1]
    user = update.effective_user

    if choice == "pm":
        if user.username:
            context.user_data['ride']['contact'] = "PM"
            context.user_data['ride']['username'] = user.username
            await show_preview_callback(query, context)
            return CONTACT_PHONE
        else:
            await query.edit_message_text(
                "❌ У вас не указан публичный @username (он скрыт или отсутствует).\n"
                "Пожалуйста, укажите номер телефона для связи:"
            )
            return CONTACT_PHONE
    else:
        await query.edit_message_text("📱 Введите номер телефона (10–11 цифр):")
        return CONTACT_PHONE

async def contact_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        clean_num = clean_phone(update.message.text)
        context.user_data['ride']['contact'] = clean_num
        context.user_data['ride']['username'] = None
        await show_preview_message(update, context)
        return CONTACT_PHONE
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите 10 или 11 цифр:")
        return CONTACT_PHONE

def build_message(ride: dict) -> str:
    from_loc = escape_html(ride['from'])
    to_loc = escape_html(ride['to'])
    comment_part = escape_html(ride['comment']) if ride.get('comment') else ""

    role_emoji = "🚗 <b>Водитель</b>" if ride['role'] == 'driver' else "👤 <b>Пассажир</b>"
    date_str = datetime.fromisoformat(ride['date']).strftime("%d.%m.%Y")
    time_slot = escape_html(ride['time'])

    msg = f"{role_emoji}\n"
    msg += f"📍 {from_loc} — {to_loc}\n"
    msg += f"📅 {date_str}\n"
    msg += f"🕗 {time_slot}\n"

    if ride['role'] == 'driver':
        msg += f"👤 Мест: {ride['seats']}\n"
    else:
        msg += f"👤 Нужно мест: {ride['seats']}\n"

    if ride['role'] == 'driver':
        price_val = ride['price']
        if price_val == "По цене билета":
            msg += "💰 Цена: По цене билета\n"
        else:
            msg += f"💰 Цена: {price_val} ₽\n"

    if ride.get('comment'):
        msg += f"💬 {comment_part}\n\n"
    else:
        msg += "\n"

    if ride['contact'] == "PM":
        username = ride.get('username')
        if username:
            safe_username = escape_html(username)
            contact_display = f"📩 Писать в личку - @{safe_username}"
        else:
            contact_display = "📩 Писать в личку"
    else:
        contact_display = format_phone(ride['contact'])

    msg += f"📞 Контакт: {contact_display}\n\n"
    msg += "Создать поездку - @poputchik_asino_bot"
    return msg

async def show_preview_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ride = context.user_data['ride']
    msg = build_message(ride)
    keyboard = [
        [InlineKeyboardButton("✅ Опубликовать", callback_data="publish_yes")],
        [InlineKeyboardButton("✏️ Изменить", callback_data="publish_edit"),
         InlineKeyboardButton("❌ Отменить", callback_data="publish_cancel")]
    ]
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_preview_callback(query, context: ContextTypes.DEFAULT_TYPE):
    ride = context.user_data['ride']
    msg = build_message(ride)
    keyboard = [
        [InlineKeyboardButton("✅ Опубликовать", callback_data="publish_yes")],
        [InlineKeyboardButton("✏️ Изменить", callback_data="publish_edit"),
         InlineKeyboardButton("❌ Отменить", callback_data="publish_cancel")]
    ]
    await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

async def publish_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    decision = query.data.split("_")[1]

    if decision != "yes":
        await query.edit_message_text("❌ Объявление отменено." if decision == "cancel" else "Начните заново командой /start.")
        return ConversationHandler.END

    try:
        ride = context.user_data['ride']
        msg = build_message(ride)

        sent = await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=msg,
            parse_mode=ParseMode.HTML
        )

        c = DB_CONN.cursor()
        c.execute('''
            INSERT INTO rides (user_id, role, from_loc, to_loc, date, time_slot, seats, comment, contact, username, message_id, price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            update.effective_user.id,
            ride['role'],
            ride['from'],
            ride['to'],
            ride['date'],
            ride['time'],
            ride['seats'],
            ride.get('comment', ''),
            ride['contact'],
            ride.get('username'),
            sent.message_id,
            ride.get('price', '')
        ))
        DB_CONN.commit()

        deletion_dt = get_deletion_time(ride)
        now = datetime.now(TZ)
        delay = max(1, (deletion_dt - now).total_seconds())

        context.job_queue.run_once(
            delete_single_ride_job,
            delay,
            data={'ride_id': c.lastrowid, 'message_id': sent.message_id}
        )

        await query.edit_message_text(
            "✅ Объявление опубликовано в канале - @poputchik_asino.\n\n"
            "Для создания новой поездки нажмите МЕНЮ - Создать поездку или /start"
        )
    except Exception as e:
        logger.error(f"Ошибка публикации: {e}", exc_info=True)
        await query.edit_message_text("❌ Ошибка при публикации. Проверьте данные.")

    return ConversationHandler.END

async def delete_single_ride_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await context.bot.delete_message(chat_id=GROUP_CHAT_ID, message_id=data['message_id'])
    except Exception:
        pass
    c = DB_CONN.cursor()
    c.execute("DELETE FROM rides WHERE id = ?", (data['ride_id'],))
    DB_CONN.commit()

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END

# === КОМАНДА /info ===
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "<b>🚗 Как создать поездку</b>\n\n"
        "1. Вернитесь в главное меню с помощью кнопки <b>«⬅️ Назад»</b> ниже.\n"
        "2. Укажите, вы <b>водитель</b> или <b>пассажир</b>.\n"
        "3. Выберите маршрут:\n"
        "   • Готовые варианты: <b>Асино — Томск</b> / <b>Томск — Асино</b>\n"
        "   • Или <b>«Указать вручную»</b>, если едете в другое место.\n"
        "4. Выберите дату поездки.\n"
        "5. Выберите время:\n"
        "   • Можно выбрать готовый слот (например, <b>07:00 - 08:00</b>)\n"
        "   • Или нажмите <b>«✏️ Указать время вручную»</b> и напишите <b>любой текст</b>:\n"
        "     → <code>15:30</code>\n"
        "     → <code>около 16 часов</code>\n"
        "     → <code>вечером, после работы</code>\n"
        "6. Водители укажут цену, пассажиры — сколько нужно мест.\n"
        "7. Оставьте комментарий (по желанию) и укажите контакт.\n\n"
        "<b>Готово!</b> Ваше объявление появится в канале @poputchik_asino."
    )
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

# === КНОПКА "НАЗАД" ===
async def back_to_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🚗 Я водитель", callback_data="role_driver")],
        [InlineKeyboardButton("👤 Я пассажир", callback_data="role_passenger")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "Все поездки публикуются в канале: @poputchik_asino\n\n"
        "Как создать поездку: нажмите МЕНЮ - Инструкция или /info\n\n"
        "Вы водитель или пассажир?",
        reply_markup=reply_markup
    )

# === ЗАПУСК ===
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_ROLE: [CallbackQueryHandler(role_selected, pattern=r"^role_")],
            SELECT_ROUTE: [CallbackQueryHandler(route_selected, pattern=r"^route_")],
            FROM_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, from_location)],
            TO_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, to_location)],
            SELECT_DATE: [CallbackQueryHandler(date_selected, pattern=r"^date_")],
            SELECT_TIME: [CallbackQueryHandler(time_selected, pattern=r"^time_")],
            MANUAL_TIME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_time_input)],
            PRICE: [
                CallbackQueryHandler(price_selected, pattern=r"^price_(text_.+|manual|\d+)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, manual_price_input)
            ],
            SEATS: [CallbackQueryHandler(seats_selected, pattern=r"^seats_\d+$")],
            COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, comment_input),
                CallbackQueryHandler(skip_comment_handler, pattern=r"^skip_comment$")
            ],
            CONTACT_METHOD: [CallbackQueryHandler(contact_method_selected, pattern=r"^contact_(phone|pm)$")],
            CONTACT_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, contact_phone_input),
                CallbackQueryHandler(publish_decision, pattern=r"^publish_(yes|edit|cancel)$")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CallbackQueryHandler(back_to_start, pattern=r"^back_to_start$"))
    application.run_polling()

if __name__ == "__main__":
    main()
