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

BOT_TOKEN = "TOKEN_BOT"
CHANNEL_ID = "ID_GROUP"
BOT_USERNAME = "NAME_BOT"

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


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Предупреждение о 48 часах
    warning_msg = "⚠️ Объявления публикуются на 48 часов и затем автоматически удаляются.\nОбъявления публикуются в канале - @asinoobyav\n\nВыберите тип объявления:"

    # Кнопки в 2 ряда
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Продать", callback_data="SELL"), InlineKeyboardButton(text="🟢 Куплю", callback_data="BUY")],
        [InlineKeyboardButton(text="🔵 Обменяю", callback_data="EXCHANGE"), InlineKeyboardButton(text="🟡 Услуги", callback_data="SERVICE")],
        [InlineKeyboardButton(text="🟣 Разное", callback_data="MISC")]
    ])
    await message.answer(warning_msg, reply_markup=keyboard)


@dp.my_chat_member()  # Отслеживаем изменения статуса участника канала
async def on_chat_member_update(update: types.ChatMemberUpdated):
    # Если пользователь только что подписался
    if update.new_chat_member.status == "member" and update.old_chat_member.status in ["left", "kicked"]:
        user_id = update.new_chat_member.user.id

        # Проверяем, не отправляли ли мы ему инструкцию ранее
        if user_id not in notified_users:
            instruction_msg = (
                "👋 Привет!\n\n"
                "Вы подписались на наш канал объявлений.\n\n"
                "Чтобы подать объявление, перейдите в бота и нажмите /start.\n\n"
                "👉 @obyavleniyaasino_bot"
            )
            try:
                await bot.send_message(chat_id=user_id, text=instruction_msg)
                notified_users.add(user_id)
            except Exception as e:
                print(f"Не удалось отправить инструкцию пользователю {user_id}: {e}")


@dp.callback_query(lambda c: c.data in ["SELL", "BUY", "EXCHANGE", "SERVICE", "MISC"])
async def handle_ad_type(callback_query: types.CallbackQuery, state: FSMContext):
    ad_type = callback_query.data
    user_id = callback_query.from_user.id
    user_data[user_id] = {"ad_type": ad_type}
    await state.set_state(AdStates.waiting_for_text)
    await callback_query.message.edit_text("📝 Введите текст объявления:")


@dp.message(AdStates.waiting_for_text)
async def handle_ad_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data[user_id]["text"] = message.text
    await state.set_state(AdStates.waiting_for_contact)

    # Кнопки выбора контакта в 2 ряда
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 В личку", callback_data="CONTACT_PRIVATE"), InlineKeyboardButton(text="📞 По телефону", callback_data="CONTACT_PHONE")],
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="CONTACT_SKIP")]
    ])
    await message.answer("Как с вами связаться?", reply_markup=keyboard)


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
            await callback_query.message.edit_text("🖼️ Пришлите до 3 фото (или /skip):")
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
        await callback_query.message.edit_text("🖼️ Пришлите до 3 фото (или /skip):")


@dp.message(AdStates.waiting_for_phone)
async def handle_phone_input(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    phone = format_phone(message.text)
    user_data[user_id]["contact_info"] = f"<tg-spoiler>{phone}</tg-spoiler>"
    await state.set_state(AdStates.waiting_for_photos)
    await message.answer("🖼️ Пришлите до 3 фото (или /skip):")


@dp.message(AdStates.waiting_for_photos)
async def handle_photos(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    if message.photo:
        if "photos" not in user_data[user_id]:
            user_data[user_id]["photos"] = []
        photo_id = message.photo[-1].file_id
        user_data[user_id]["photos"].append(photo_id)

        if len(user_data[user_id]["photos"]) >= 3:
            await publish_ad_with_auto_delete(message, user_id)
        else:
            await message.answer(f"📸 Фото добавлено. Осталось: {3 - len(user_data[user_id]['photos'])}. Продолжайте или /skip.")

    elif message.text == "/skip":
        await publish_ad_with_auto_delete(message, user_id)

    else:
        await message.answer("⚠️ Это не фото. Пришлите фото или /skip.")


async def publish_ad_with_auto_delete(message: types.Message, user_id: int):
    data = user_data[user_id]
    ad_type_code = data["ad_type"]
    ad_text = data["text"]
    contact_info = data["contact_info"]

    header, emoji_item = ad_type_map.get(ad_type_code, ("❓ Неизвестный", "❓"))

    # Формат сообщения с разделителем
    message_html = (
        f"{header}\n\n"
        f"{emoji_item} {ad_text}\n\n"
        f"📞 Контакт: {contact_info}\n\n"
        f"==========\n"
        f"📌 Разместите свое объявление — @{BOT_USERNAME}\n"
    )

    try:
        photos = data.get("photos", [])
        if photos:
            media_group = []
            for i, photo_id in enumerate(photos):
                if i == 0:
                    media_group.append(types.InputMediaPhoto(media=photo_id, caption=message_html, parse_mode="HTML"))
                else:
                    media_group.append(types.InputMediaPhoto(media=photo_id))
            sent_messages = await bot.send_media_group(chat_id=CHANNEL_ID, media=media_group)
            msg_ids = [m.message_id for m in sent_messages]
        else:
            sent_message = await bot.send_message(chat_id=CHANNEL_ID, text=message_html, parse_mode="HTML")
            msg_ids = [sent_message.message_id]

        # Запускаем задачу на удаление через 48 часов
        asyncio.create_task(auto_delete_messages(msg_ids))

        await message.answer("✅ Ваше объявление опубликовано и будет удалено через 48 часов.")

    except Exception as e:
        await message.answer(f"❌ Ошибка публикации: {e}")

    # Очистка данных
    user_data.pop(user_id, None)


async def auto_delete_messages(msg_ids: list):
    await asyncio.sleep(172800)  # 48 часов
    for msg_id in msg_ids:
        try:
            await bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
            print(f"Сообщение {msg_id} удалено из {CHANNEL_ID}")
        except Exception as e:
            print(f"Ошибка при удалении {msg_id}: {e}")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
