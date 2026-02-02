import asyncio
import re
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# === Состояния ===
class AdStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_photos = State()      # фото ДО контакта
    waiting_for_contact = State()
    waiting_for_phone = State()

# === Хранилище ===
user_data = {}

# === Типы объявлений ===
ad_type_map = {
    "SELL": ("🔴 Продам", "🛍️"),
    "BUY": ("🟢 Куплю", "📥"),
    "EXCHANGE": ("🔵 Обменяю", "🔄"),
    "SERVICE": ("🟡 Услуги", "🔧"),
    "MISC": ("🟣 Разное", "📦")
}

# === Настройки ===
BOT_TOKEN = "7979907582:AAGsD6DJsYH-NXxoVV4TWPc26F_SG8PLStQ"
CHANNEL_ID = "-1003533127290"
BOT_USERNAME = "asinoobyav_bot"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

notified_users = set()

# === Вспомогательные функции ===
def format_phone(phone_str: str) -> str:
    digits = re.sub(r'\D', '', phone_str)
    if len(digits) == 11 and digits.startswith('8'):
        return f"8 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:11]}"
    elif len(digits) == 10 and digits.startswith('9'):
        return f"8 {digits[0:3]} {digits[3:6]} {digits[6:8]} {digits[8:10]}"
    elif len(digits) == 11 and digits.startswith('7'):
        return f"8 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:11]}"
    else:
        return digits


# === Команда /info ===
@dp.message(Command("info"))
async def cmd_info(message: types.Message):
    info_text = (
        "📋 Как подать объявление:\n\n"
        "1. Нажмите /start\n"
        "2. Выберите тип объявления (Продать, Куплю и т.д.)\n"
        "3. Введите текст объявления (можно пропустить)\n"
        "4. Пришлите до 3 фото (можно пропустить)\n"
        "5. Укажите способ связи — в личку или по телефону\n"
        "6. Готово! Ваше объявление появится в канале @asinoobyav"
    )
    await message.answer(info_text)


# === Команда /start ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    start_msg = (
        "Объявления публикуются в канале - @asinoobyav\n\n"
        "Как создать объявление? - /info\n\n"
        "Выберите тип объявления:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Продать", callback_data="SELL"), InlineKeyboardButton(text="🟢 Куплю", callback_data="BUY")],
        [InlineKeyboardButton(text="🔵 Обменяю", callback_data="EXCHANGE"), InlineKeyboardButton(text="🟡 Услуги", callback_data="SERVICE")],
        [InlineKeyboardButton(text="🟣 Разное", callback_data="MISC")]
    ])
    await message.answer(start_msg, reply_markup=keyboard)


# === Подписка на канал ===
@dp.my_chat_member()
async def on_chat_member_update(update: types.ChatMemberUpdated):
    if update.new_chat_member.status == "member" and update.old_chat_member.status in ["left", "kicked"]:
        user_id = update.new_chat_member.user.id
        if user_id not in notified_users:
            instruction_msg = (
                "👋 Привет!\n\n"
                "Вы подписались на наш канал объявлений.\n\n"
                "Чтобы подать объявление, перейдите в бота и нажмите /start.\n\n"
                "👉 @asinoobyav_bot"
            )
            try:
                await bot.send_message(chat_id=user_id, text=instruction_msg)
                notified_users.add(user_id)
            except Exception as e:
                print(f"Не удалось отправить инструкцию пользователю {user_id}: {e}")


# === Выбор типа объявления ===
@dp.callback_query(lambda c: c.data in ["SELL", "BUY", "EXCHANGE", "SERVICE", "MISC"])
async def handle_ad_type(callback_query: types.CallbackQuery, state: FSMContext):
    ad_type = callback_query.data
    user_id = callback_query.from_user.id
    user_data[user_id] = {"ad_type": ad_type}
    await state.set_state(AdStates.waiting_for_text)

    skip_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="SKIP_TEXT")]
    ])
    await callback_query.message.edit_text("📝 Введите текст объявления:", reply_markup=skip_kb)


# === Пропустить текст ===
@dp.callback_query(lambda c: c.data == "SKIP_TEXT")
async def skip_ad_text(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    user_data[user_id] = user_data.get(user_id, {})
    user_data[user_id]["text"] = ""
    await state.set_state(AdStates.waiting_for_photos)
    try:
        await callback_query.message.delete()
    except:
        pass
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить / продолжить", callback_data="SKIP_PHOTOS")]
    ])
    await callback_query.message.answer("🖼️ Пришлите до 3 фото:", reply_markup=kb)


# === Ввод текста ===
@dp.message(AdStates.waiting_for_text)
async def handle_ad_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data[user_id] = user_data.get(user_id, {})
    user_data[user_id]["text"] = message.text
    await state.set_state(AdStates.waiting_for_photos)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить / продолжить", callback_data="SKIP_PHOTOS")]
    ])
    await message.answer("🖼️ Пришлите до 3 фото:", reply_markup=kb)


# === Обработка фото: новое сообщение под каждым фото ===
@dp.message(AdStates.waiting_for_photos)
async def handle_photos(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    if not message.photo:
        await message.answer("⚠️ Это не фото. Пришлите изображение.")
        return

    if "photos" not in user_data[user_id]:
        user_data[user_id]["photos"] = []
    user_data[user_id]["photos"].append(message.photo[-1].file_id)

    current_count = len(user_data[user_id]["photos"])

    if current_count >= 3:
        # Все фото загружены — переходим к контакту
        await proceed_to_contact(message, state, user_id)
    else:
        # Отправляем новое сообщение ПОД фото
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить / продолжить", callback_data="SKIP_PHOTOS")]
        ])
        status_msg = (
            f"📸 Фото добавлено ({current_count}/3).\n"
            f"Продолжайте присылать или нажмите кнопку ниже:"
        )
        await message.answer(status_msg, reply_markup=kb)


# === Пропустить фото ===
@dp.callback_query(lambda c: c.data == "SKIP_PHOTOS")
async def skip_photos(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    # Удаляем сообщение с кнопкой, чтобы не оставлять мусор
    try:
        await callback_query.message.delete()
    except:
        pass
    await proceed_to_contact(callback_query, state, user_id)


# === Переход к контакту ===
async def proceed_to_contact(message_or_callback, state: FSMContext, user_id: int):
    await state.set_state(AdStates.waiting_for_contact)

    if isinstance(message_or_callback, types.CallbackQuery):
        chat_id = message_or_callback.message.chat.id
    else:
        chat_id = message_or_callback.chat.id

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 В личку", callback_data="CONTACT_PRIVATE"), InlineKeyboardButton(text="📞 По телефону", callback_data="CONTACT_PHONE")],
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="CONTACT_SKIP")]
    ])
    contact_msg = await bot.send_message(chat_id, "Как с вами связаться?", reply_markup=keyboard)
    user_data[user_id]["contact_msg_id"] = contact_msg.message_id


# === Выбор контакта ===
@dp.callback_query(lambda c: c.data in ["CONTACT_PRIVATE", "CONTACT_PHONE", "CONTACT_SKIP"])
async def handle_contact_choice(callback_query: types.CallbackQuery, state: FSMContext):
    contact_type = callback_query.data
    user_id = callback_query.from_user.id
    user_data[user_id]["contact_type"] = contact_type

    msg_id = user_data[user_id].get("contact_msg_id")
    if msg_id:
        try:
            await bot.delete_message(callback_query.message.chat.id, msg_id)
        except:
            pass

    if contact_type == "CONTACT_PRIVATE":
        username = callback_query.from_user.username
        if username:
            user_data[user_id]["contact_info"] = f"<tg-spoiler>@{username}</tg-spoiler>"
            await publish_ad(callback_query.message, user_id)
            await state.clear()
        else:
            await state.set_state(AdStates.waiting_for_phone)
            await callback_query.message.answer(
                "У вас скрыт никнейм. Введите номер телефона для связи:"
            )
    elif contact_type == "CONTACT_PHONE":
        await state.set_state(AdStates.waiting_for_phone)
        await callback_query.message.answer("📞 Введите номер телефона:")
    elif contact_type == "CONTACT_SKIP":
        user_data[user_id]["contact_info"] = "<tg-spoiler>Не указан</tg-spoiler>"
        await publish_ad(callback_query.message, user_id)
        await state.clear()


# === Ввод телефона ===
@dp.message(AdStates.waiting_for_phone)
async def handle_phone_input(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    phone = format_phone(message.text)
    user_data[user_id]["contact_info"] = f"<tg-spoiler>{phone}</tg-spoiler>"
    await publish_ad(message, user_id)
    await state.clear()


# === Публикация объявления ===
async def publish_ad(message_or_callback: types.Message | types.CallbackQuery, user_id: int):
    data = user_data.get(user_id)
    if not data:
        return

    ad_text = data.get("text", "").strip()
    photos = data.get("photos", [])
    contact_info_raw = data.get("contact_info", "<tg-spoiler>Не указан</tg-spoiler>")

    has_text = bool(ad_text)
    has_photos = len(photos) > 0

    if not (has_text or has_photos):
        error_msg = (
            "❌ Объявление не может быть опубликовано:\n"
            "Укажите **текст объявления** или пришлите **фото**.\n\n"
            "Контакт сам по себе не является объявлением."
        )
        restart_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Подать объявление снова", callback_data="RESTART_AD")]
        ])
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(error_msg, reply_markup=restart_kb)
        else:
            await message_or_callback.answer(error_msg, reply_markup=restart_kb)
        user_data.pop(user_id, None)
        return

    ad_type_code = data["ad_type"]
    header, emoji_item = ad_type_map.get(ad_type_code, ("❓ Неизвестный", "❓"))

    lines = ["\u200B"]
    lines.append(header)

    if ad_text:
        lines.append("")
        lines.append(f"{emoji_item} {ad_text}")

    lines.append("")
    lines.append(f"📞 Контакт: {contact_info_raw}")

    lines.append("")
    lines.append("==========")
    lines.append(f"📌 Разместите свое объявление — @{BOT_USERNAME}")

    message_html = "\n".join(lines)

    try:
        if photos:
            media_group = []
            for i, photo_id in enumerate(photos):
                if i == 0:
                    media_group.append(types.InputMediaPhoto(media=photo_id, caption=message_html, parse_mode="HTML"))
                else:
                    media_group.append(types.InputMediaPhoto(media=photo_id))
            await bot.send_media_group(chat_id=CHANNEL_ID, media=media_group)
        else:
            await bot.send_message(chat_id=CHANNEL_ID, text=message_html, parse_mode="HTML")

        final_msg = (
            "✅ Ваше объявление опубликовано в канале - @asinoobyav.\n\n"
            "Чтобы создать новое объявление нажмите - /start"
        )
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(final_msg)
        else:
            await message_or_callback.answer(final_msg)

    except Exception as e:
        error_msg = f"❌ Ошибка публикации: {e}"
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(error_msg)
        else:
            await message_or_callback.answer(error_msg)

    user_data.pop(user_id, None)


# === Кнопка "Подать объявление снова" ===
@dp.callback_query(lambda c: c.data == "REASTART_AD")
async def restart_ad(callback_query: types.CallbackQuery, state: FSMContext):
    await state.clear()
    start_msg = (
        "Объявления публикуются в канале - @asinoobyav\n\n"
        "Как создать объявление? - /info\n\n"
        "Выберите тип объявления:"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Продать", callback_data="SELL"), InlineKeyboardButton(text="🟢 Куплю", callback_data="BUY")],
        [InlineKeyboardButton(text="🔵 Обменяю", callback_data="EXCHANGE"), InlineKeyboardButton(text="🟡 Услуги", callback_data="SERVICE")],
        [InlineKeyboardButton(text="🟣 Разное", callback_data="MISC")]
    ])
    await callback_query.message.answer(start_msg, reply_markup=keyboard)
    await callback_query.answer()


# === Запуск ===
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())