import os
import json
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton, WebAppInfo, ReplyKeyboardMarkup
from aiogram.utils import executor
from aiogram.dispatcher.filters import Text
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage

# ========== КОНФИГ ==========
BOT_TOKEN = "8769773881:AAHTAqNMM69ddflLgANr2JIbBcJbuUYAPNM"  # ВСТАВЬ СВОЙ ТОКЕН
ADMIN_IDS = [6141160793]
WEB_APP_URL = "https://api-production-7faf.up.railway.app/miniapp"

# ========== БАЗА ДАННЫХ (ОБЩАЯ ЧЕРЕЗ VOLUME) ==========
# Создаём папку /data если её нет
os.makedirs("/data", exist_ok=True)

db_conn = sqlite3.connect("/data/sports_bot.db", check_same_thread=False)
cursor = db_conn.cursor()

# Создаём таблицы
cursor.execute('''
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, description TEXT, options TEXT,
        status TEXT DEFAULT 'active', winner TEXT, created_at TIMESTAMP
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, event_id INTEGER, selected_option TEXT,
        bet_time TIMESTAMP, is_win BOOLEAN DEFAULT 0, points_earned INTEGER DEFAULT 0
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT, full_name TEXT, points INTEGER DEFAULT 0
    )
''')
db_conn.commit()

def add_event(title, description, options):
    cursor.execute(
        "INSERT INTO events (title, description, options, status, created_at) VALUES (?, ?, ?, 'active', ?)",
        (title, description, json.dumps(options), datetime.now())
    )
    db_conn.commit()
    return cursor.lastrowid

def get_active_events():
    cursor.execute("SELECT * FROM events WHERE status = 'active' ORDER BY created_at DESC")
    return cursor.fetchall()

def get_event(event_id):
    cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
    return cursor.fetchone()

def finish_event(event_id, winner_option):
    event = get_event(event_id)
    options = json.loads(event[3])
    coefficient = options.get(winner_option, 1.0)
    points_to_add = int(10 * coefficient)
    
    cursor.execute("SELECT user_id, selected_option FROM bets WHERE event_id = ?", (event_id,))
    bets = cursor.fetchall()
    winners_count = 0
    for user_id, selected in bets:
        if selected == winner_option:
            cursor.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points_to_add, user_id))
            cursor.execute("UPDATE bets SET is_win = 1, points_earned = ? WHERE event_id = ? AND user_id = ?", 
                          (points_to_add, event_id, user_id))
            winners_count += 1
    cursor.execute("UPDATE events SET status = 'finished', winner = ? WHERE id = ?", (winner_option, event_id))
    db_conn.commit()
    return winners_count, points_to_add

def place_bet(user_id, event_id, selected_option):
    cursor.execute("SELECT id FROM bets WHERE user_id = ? AND event_id = ?", (user_id, event_id))
    if cursor.fetchone():
        return False
    cursor.execute(
        "INSERT INTO bets (user_id, event_id, selected_option, bet_time) VALUES (?, ?, ?, ?)",
        (user_id, event_id, selected_option, datetime.now())
    )
    db_conn.commit()
    return True

def register_user(user_id, username, full_name):
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, full_name, points) VALUES (?, ?, ?, 0)",
                   (user_id, username, full_name))
    db_conn.commit()

def get_user_points(user_id):
    cursor.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    return res[0] if res else 0

def get_leaderboard():
    cursor.execute("SELECT full_name, username, points FROM users ORDER BY points DESC LIMIT 10")
    return [(row[0] or row[1], row[2]) for row in cursor.fetchall()]

# ========== ИНИЦИАЛИЗАЦИЯ БОТА ==========
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=storage)

# Клавиатура
web_app = WebAppInfo(url=WEB_APP_URL)
main_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
main_keyboard.add(KeyboardButton("Активные события"))
main_keyboard.add(KeyboardButton("Мой рейтинг"), KeyboardButton("Таблица лидеров"))
main_keyboard.add(KeyboardButton("📱 Открыть прогнозы", web_app=web_app))

class AddEvent(StatesGroup):
    title = State()
    description = State()
    options = State()

# ========== ОБРАБОТЧИКИ ==========
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    user = message.from_user
    register_user(user.id, user.username, user.full_name)
    await message.answer(
        f"🏅 Добро пожаловать, {user.full_name}!\n\n"
        f"📊 Правильный прогноз = 10 × коэффициент\n\n"
        f"📝 Команды:\n"
        f"/add_event - добавить событие (админ)\n"
        f"/finish ID Победитель - завершить событие (админ)",
        reply_markup=main_keyboard
    )

@dp.message_handler(lambda message: message.text == "Активные события")
async def show_events(message: types.Message):
    events = get_active_events()
    if not events:
        await message.answer("😔 Нет активных событий\n\nДобавь через /add_event")
        return
    for event in events:
        event_id, title, description, options_json, status, winner, created_at = event
        options = json.loads(options_json)
        options_text = "\n".join([f"  • {opt} — x{coef}" for opt, coef in options.items()])
        buttons = [[InlineKeyboardButton(f"{opt} (x{coef})", callback_data=f"bet_{event_id}_{opt}")] for opt, coef in options.items()]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(
            f"⚽️ *{title}*\n\n📝 {description}\n\n📊 *Варианты:*\n{options_text}",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

@dp.message_handler(lambda message: message.text == "Мой рейтинг")
async def my_rating(message: types.Message):
    points = get_user_points(message.from_user.id)
    await message.answer(f"📊 *Твой счёт: {points} баллов*", parse_mode="Markdown")

@dp.message_handler(lambda message: message.text == "Таблица лидеров")
async def leaderboard(message: types.Message):
    leaders = get_leaderboard()
    if not leaders:
        await message.answer("🏆 Таблица лидеров пуста\n\nБудь первым!")
        return
    text = "🏆 *ТАБЛИЦА ЛИДЕРОВ* 🏆\n\n"
    for i, (name, points) in enumerate(leaders, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} *{name}* — {points} баллов\n"
    await message.answer(text, parse_mode="Markdown")

@dp.callback_query_handler(lambda c: c.data.startswith("bet_"))
async def place_bet_callback(callback: types.CallbackQuery):
    _, event_id_str, option = callback.data.split("_", 2)
    event_id = int(event_id_str)
    user_id = callback.from_user.id
    event = get_event(event_id)
    if not event or event[4] != 'active':
        await callback.answer("⏰ Событие завершено!", show_alert=True)
        return
    register_user(user_id, callback.from_user.username, callback.from_user.full_name)
    if place_bet(user_id, event_id, option):
        options = json.loads(event[3])
        coef = options.get(option, 1.0)
        await callback.answer(f"✅ Прогноз принят! {option} (x{coef})")
        await callback.message.answer(f"✨ Прогноз принят!\n{option} (x{coef})")
    else:
        await callback.answer("⚠️ Ты уже делал прогноз!", show_alert=True)

@dp.message_handler(commands=['add_event'])
async def add_event_start(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        await AddEvent.title.set()
        await message.answer("📝 Введите *название* события:", parse_mode="Markdown")

@dp.message_handler(state=AddEvent.title)
async def add_event_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await AddEvent.next()
    await message.answer("📝 Введите *описание* события:", parse_mode="Markdown")

@dp.message_handler(state=AddEvent.description)
async def add_event_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await AddEvent.next()
    await message.answer(
        "📝 Введите *варианты* с коэффициентами\n\n"
        "Формат: `Вариант1:коэффициент, Вариант2:коэффициент`\n"
        "Пример: `Победа А:3.5, Ничья:3.0, Победа Б:3.2`",
        parse_mode="Markdown"
    )

@dp.message_handler(state=AddEvent.options)
async def add_event_opts(message: types.Message, state: FSMContext):
    parts = [x.strip() for x in message.text.split(",")]
    options = {}
    for part in parts:
        if ":" in part:
            name, coef = part.split(":")
            options[name.strip()] = float(coef.strip())
        else:
            options[part] = 1.0
    if len(options) < 2:
        await message.answer("❌ Нужно минимум 2 варианта!", parse_mode="Markdown")
        return
    data = await state.get_data()
    event_id = add_event(data['title'], data['description'], options)
    await message.answer(
        f"✅ *Событие добавлено!*\n\n"
        f"📋 {data['title']}\n"
        f"📊 {', '.join([f'{k} (x{v})' for k,v in options.items()])}\n\n"
        f"🔢 ID: `{event_id}`\n"
        f"Завершить: `/finish {event_id} Победитель`",
        parse_mode="Markdown"
    )
    await state.finish()

@dp.message_handler(commands=['finish'])
async def finish_event_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав!")
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("📝 Использование: `/finish ID Победитель`", parse_mode="Markdown")
        return
    _, event_id_str, winner = parts
    event_id = int(event_id_str)
    event = get_event(event_id)
    if not event:
        await message.answer(f"❌ Событие не найдено!")
        return
    if event[4] != 'active':
        await message.answer(f"⚠️ Событие уже завершено!", parse_mode="Markdown")
        return
    winners_count, points = finish_event(event_id, winner)
    await message.answer(
        f"✅ *Событие завершено!*\n\n"
        f"📋 {event[1]}\n"
        f"🏆 Победитель: *{winner}*\n"
        f"💰 Начислено: *{points} баллов* ({winners_count} чел.)",
        parse_mode="Markdown"
    )


@dp.message_handler(commands=['delete_event'])
async def delete_event_cmd(message: types.Message):
    # Проверяем, что команду выполняет администратор
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет прав для этой команды!")
        return

    # Разбираем ID события из сообщения (формат: /delete_event 123)
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "📝 *Как удалить событие:*\n\n"
            "`/delete_event ID_события`\n\n"
            "Пример: `/delete_event 5`\n"
            "Чтобы узнать ID, используйте `/list_events`.",
            parse_mode="Markdown"
        )
        return

    try:
        event_id = int(parts[1])
    except ValueError:
        await message.answer("❌ ID события должен быть числом!")
        return

    # Проверяем, существует ли событие в базе данных
    cursor.execute("SELECT id, title, status FROM events WHERE id = ?", (event_id,))
    event = cursor.fetchone()

    if not event:
        await message.answer(f"❌ Событие с ID `{event_id}` не найдено!", parse_mode="Markdown")
        return

    # Удаляем событие из базы данных
    cursor.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db_conn.commit()

    # Сообщаем об успешном удалении
    await message.answer(f"✅ Событие *{event[1]}* (ID: {event_id}) было успешно удалено из базы данных.", parse_mode="Markdown")




# ========== АДМИН-ПАНЕЛЬ (УПРАВЛЕНИЕ СОБЫТИЯМИ) ==========
@dp.message_handler(commands=['admin'])
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав!")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📋 Список событий", callback_data="admin_list_events")],
        [InlineKeyboardButton("➕ Добавить событие", callback_data="admin_add_event_short")]
    ])
    await message.answer("🔧 *Админ-панель*\n\nВыбери действие:", parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data == "admin_list_events")
async def admin_list_events(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет прав!")
        return
    
    cursor.execute("SELECT id, title, status FROM events ORDER BY id DESC")
    events = cursor.fetchall()
    
    if not events:
        await callback.message.answer("📭 Нет событий в базе")
        await callback.answer()
        return
    
    for event in events:
        event_id, title, status = event
        status_emoji = "🟢" if status == "active" else "🔴"
        status_text = "активно" if status == "active" else "завершено"
        
        buttons = []
        if status == "active":
            buttons.append(InlineKeyboardButton("🏁 Завершить", callback_data=f"admin_finish_{event_id}"))
        buttons.append(InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_delete_{event_id}"))
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
        
        await callback.message.answer(
            f"{status_emoji} *ID {event_id}:* {title}\n📌 Статус: {status_text}",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_add_event_short")
async def admin_add_event_short(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет прав!")
        return
    
    await callback.message.answer("📝 Используй команду `/add_event` для добавления события")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_finish_"))
async def admin_finish_event_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет прав!")
        return
    
    event_id = int(callback.data.split("_")[2])
    event = get_event(event_id)
    
    if not event:
        await callback.answer("❌ Событие не найдено!", show_alert=True)
        return
    
    if event[4] != 'active':
        await callback.answer("⚠️ Событие уже завершено!", show_alert=True)
        return
    
    options = json.loads(event[3])
    buttons = [[InlineKeyboardButton(f"🏆 {opt}", callback_data=f"admin_winner_{event_id}_{opt}")] for opt in options.keys()]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(
        f"📋 *{event[1]}*\n\nВыбери победителя:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_winner_"))
async def admin_set_winner(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет прав!")
        return
    
    _, _, event_id_str, winner = callback.data.split("_", 3)
    event_id = int(event_id_str)
    
    winners_count, points = finish_event(event_id, winner)
    
    await callback.message.delete()
    await callback.message.answer(
        f"✅ *Событие завершено!*\n\n"
        f"🏆 Победитель: *{winner}*\n"
        f"💰 Начислено: *{points} баллов* ({winners_count} чел.)",
        parse_mode="Markdown"
    )
    await callback.answer()

# ========== УДАЛЕНИЕ СОБЫТИЙ ==========
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_delete_"))
async def admin_delete_event_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    event_id = int(callback.data.split("_")[2])
    
    cursor.execute("SELECT id, title FROM events WHERE id = ?", (event_id,))
    event = cursor.fetchone()
    
    if not event:
        await callback.answer("❌ Событие не найдено!", show_alert=True)
        return
    
    # Удаляем событие
    cursor.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db_conn.commit()
    
    # Удаляем связанные прогнозы
    cursor.execute("DELETE FROM bets WHERE event_id = ?", (event_id,))
    db_conn.commit()
    
    await callback.message.delete()
    await callback.answer(f"✅ Событие '{event[1]}' удалено!", show_alert=True)
    
    # Отправляем подтверждение в чат
    await callback.message.answer(f"🗑 Событие *{event[1]}* (ID: {event_id}) удалено из базы.", parse_mode="Markdown")

@dp.message_handler(commands=['delete_event'])
async def delete_event_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав!")
        return
    
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "📝 *Как удалить событие:*\n\n`/delete_event ID`\n\nПример: `/delete_event 5`\n\nИспользуй `/admin` → 'Список событий' чтобы увидеть ID",
            parse_mode="Markdown"
        )
        return
    
    try:
        event_id = int(parts[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом!")
        return
    
    cursor.execute("SELECT id, title FROM events WHERE id = ?", (event_id,))
    event = cursor.fetchone()
    
    if not event:
        await message.answer(f"❌ Событие с ID `{event_id}` не найдено!", parse_mode="Markdown")
        return
    
    cursor.execute("DELETE FROM events WHERE id = ?", (event_id,))
    cursor.execute("DELETE FROM bets WHERE event_id = ?", (event_id,))
    db_conn.commit()
    
    await message.answer(f"✅ Событие *{event[1]}* (ID: {event_id}) удалено!", parse_mode="Markdown")



@dp.message_handler(commands=['list_events'])
async def list_events_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав!")
        return
    
    cursor.execute("SELECT id, title, status FROM events ORDER BY id DESC")
    events = cursor.fetchall()
    
    if not events:
        await message.answer("📭 Нет событий")
        return
    
    text = "📋 *Список событий:*\n\n"
    for event in events:
        status_emoji = "🟢" if event[2] == "active" else "🔴"
        text += f"{status_emoji} ID: `{event[0]}` — {event[1]}\n"
    
    await message.answer(text, parse_mode="Markdown")


# ========== ЗАПУСК ==========
if __name__ == "__main__":
    print("🚀 Бот спортивных прогнозов запущен!")
    print("👑 Админ: /add_event, /finish")
    executor.start_polling(dp, skip_updates=True)
