import asyncio
import re
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# FSM состояния
class AdStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_contact = State()
    waiting_for_phone = State()
    waiting_for_photos = State()

# Хранилище данных
user_data = {}

# Карта типов объявлений
ad_type_map = {
    "SELL": ("🔴 Продам", "🛍️"),
    "BUY": ("🟢 Куплю", "📥"),
    "EXCHANGE": ("🔵 Обменяю", "🔄"),
    "SERVICE": ("🟡 Услуги", "🔧"),
    "MISC": ("🟣 Разное", "📦")
}

BOT_TOKEN = "8395318503:AAHW53QFGef_chHRoC8T3wAluKV5EaLFX4U"
CHANNEL_ID = "-1002498080112"
BOT_USERNAME = "asinoobyav_bot"  # ← Убедитесь, что это правильное имя

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Храним ID пользователей, которым уже отправили инструкцию
notified_users = set()

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


# === /info ===
@dp.message(Command("info"))
async def cmd_info(message: types.Message):
    info_text = (
        "📋 Как подать объявление:\n\n"
        "1. Нажмите /start\n"
        "2. Выберите тип объявления (Продам, Куплю и т.д.)\n"
        "3. Введите текст объявления (можно пропустить)\n"
        "4. Укажите способ связи — в личку или по телефону\n"
        "5. Пришлите до 3 фото (или нажмите «Пропустить / продолжить»)\n"
        "6. Готово! Ваше объявление появится в канале @asinoobyav"
    )
    await message.answer(info_text)


# === /start ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    start_msg = (
        "Объявления публикуются в канале - @asinoobyav\n\n"
        "Как создать объявление? - /info\n\n"
        "Выберите тип объявления:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Продам", callback_data="SELL"), InlineKeyboardButton(text="🟢 Куплю", callback_data="BUY")],
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
    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id]["text"] = ""
    await state.set_state(AdStates.waiting_for_contact)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 В личку", callback_data="CONTACT_PRIVATE"), InlineKeyboardButton(text="📞 По телефону", callback_data="CONTACT_PHONE")],
        [InlineKeyboardButton(text="⏭️ Пропустить / продолжить", callback_data="SKIP_STEP")]
    ])
    await callback_query.message.edit_text("Как с вами связаться?", reply_markup=keyboard)


# === Ввод текста (если не пропущен) ===
@dp.message(AdStates.waiting_for_text)
async def handle_ad_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data[user_id]["text"] = message.text
    await state.set_state(AdStates.waiting_for_contact)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 В личку", callback_data="CONTACT_PRIVATE"), InlineKeyboardButton(text="📞 По телефону", callback_data="CONTACT_PHONE")],
        [InlineKeyboardButton(text="⏭️ Пропустить / продолжить", callback_data="SKIP_STEP")]
    ])
    await message.answer("Как с вами связаться?", reply_markup=keyboard)


# === Выбор контакта ===
@dp.callback_query(lambda c: c.data in ["CONTACT_PRIVATE", "CONTACT_PHONE", "CONTACT_SKIP"])
async def handle_contact_choice(callback_query: types.CallbackQuery, state: FSMContext):
    contact_type = callback_query.data
    user_id = callback_query.from_user.id
    user_data[user_id]["contact_type"] = contact_type

    if contact_type == "CONTACT_PRIVATE":
        username = callback_query.from_user.username
        if username:
            user_data[user_id]["contact_info"] = f"<tg-spoiler>@{username}</tg-spoiler>"
            await state.set_state(AdStates.waiting_for_photos)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏭️ Пропустить / продолжить", callback_data="SKIP_STEP")]
            ])
            await callback_query.message.edit_text("🖼️ Пришлите до 3 фото:", reply_markup=kb)
        else:
            await state.set_state(AdStates.waiting_for_phone)
            await callback_query.message.edit_text(
                "У вас скрыт никнейм. Введите номер телефона для связи:"
            )
    elif contact_type == "CONTACT_PHONE":
        await state.set_state(AdStates.waiting_for_phone)
        await callback_query.message.edit_text("📞 Введите номер телефона:")
    elif contact_type == "CONTACT_SKIP":
        user_data[user_id]["contact_info"] = "<tg-spoiler>Не указан</tg-spoiler>"
        await state.set_state(AdStates.waiting_for_photos)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить / продолжить", callback_data="SKIP_STEP")]
        ])
        await callback_query.message.edit_text("🖼️ Пришлите до 3 фото:", reply_markup=kb)


# === Ввод телефона ===
@dp.message(AdStates.waiting_for_phone)
async def handle_phone_input(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    phone = format_phone(message.text)
    user_data[user_id]["contact_info"] = f"<tg-spoiler>{phone}</tg-spoiler>"
    await state.set_state(AdStates.waiting_for_photos)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить / продолжить", callback_data="SKIP_STEP")]
    ])
    await message.answer("🖼️ Пришлите до 3 фото:", reply_markup=kb)


# === Обработка фото ===
@dp.message(AdStates.waiting_for_photos)
async def handle_photos(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    if message.photo:
        if "photos" not in user_data[user_id]:
            user_data[user_id]["photos"] = []
        photo_id = message.photo[-1].file_id
        user_data[user_id]["photos"].append(photo_id)

        if len(user_data[user_id]["photos"]) >= 3:
            await publish_ad(message, user_id)
            await state.clear()
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏭️ Пропустить / продолжить", callback_data="SKIP_STEP")]
            ])
            await message.answer(
                f"📸 Фото добавлено. Осталось: {3 - len(user_data[user_id]['photos'])}.\n"
                f"Продолжайте присылать фото или нажмите кнопку ниже:",
                reply_markup=kb
            )
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить / продолжить", callback_data="SKIP_STEP")]
        ])
        await message.answer("⚠️ Это не фото. Пришлите изображение или нажмите кнопку ниже:", reply_markup=kb)


# === Пропустить фото (или завершить) ===
@dp.callback_query(lambda c: c.data == "SKIP_STEP")
async def skip_photos_step(callback_query: types.CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state == AdStates.waiting_for_photos:
        user_id = callback_query.from_user.id
        await publish_ad(callback_query.message, user_id)
        await state.clear()
    else:
        await callback_query.answer("Эта кнопка доступна только при добавлении фото.", show_alert=True)


# === Публикация объявления ===
async def publish_ad(message_or_callback: types.Message | types.CallbackQuery, user_id: int):
    data = user_data.get(user_id)
    if not data:
        return

    ad_type_code = data["ad_type"]
    ad_text = data.get("text", "").strip()
    contact_info = data["contact_info"]

    header, emoji_item = ad_type_map.get(ad_type_code, ("❓ Неизвестный", "❓"))

    # Формируем тело объявления
    parts = [header]

    # Добавляем текст только если он не пустой
    if ad_text:
        parts.append(f"{emoji_item} {ad_text}")

    parts.extend([
        f"📞 Контакт: {contact_info}",
        "",
        "==========",
        f"📌 Разместите свое объявление — @{BOT_USERNAME}"
    ])

    message_html = "\n".join(parts)

    try:
        photos = data.get("photos", [])
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

        # ✅ Финальное сообщение
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


# === Запуск ===
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())