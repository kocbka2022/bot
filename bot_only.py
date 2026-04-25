import os
import json
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.dispatcher.filters import Text
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage

# ========== КОНФИГ ==========
BOT_TOKEN = "8769773881:AAGUNmK-uTRxIQClaWHVQpr3UomSDVlstiI"
ADMIN_IDS = [6141160793]

# ========== БАЗА ДАННЫХ ==========
db_conn = sqlite3.connect("sports_bot.db", check_same_thread=False)
cursor = db_conn.cursor()

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
    cursor.execute("INSERT INTO events (title, description, options, status, created_at) VALUES (?, ?, ?, 'active', ?)",
                   (title, description, json.dumps(options), datetime.now()))
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
    cursor.execute("INSERT INTO bets (user_id, event_id, selected_option, bet_time) VALUES (?, ?, ?, ?)",
                   (user_id, event_id, selected_option, datetime.now()))
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

# ========= ТЕЛЕГРАМ БОТ =========

storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=storage)

from aiogram.types import KeyboardButton, WebAppInfo, ReplyKeyboardMarkup

# URL Mini App (замени после деплоя второго сервиса)
WEB_APP_URL = "https://bot-production-b860.up.railway.app/miniapp"
web_app = WebAppInfo(url=WEB_APP_URL)

main_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
main_keyboard.add(KeyboardButton("🟢 Активные события"))
main_keyboard.add(KeyboardButton("🔴 Мой рейтинг"), KeyboardButton("🔵 Таблица лидеров"))
main_keyboard.add(KeyboardButton("📱 Открыть прогнозы", web_app=web_app))

class AddEvent(StatesGroup):
    title = State()
    description = State()
    options = State()

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

@dp.message_handler(Text(equals="📋 Активные события"))
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
        await callback.message.answer(f"✨ Прогноз принят!\n{option} (x{coef})\n💰 Потенциальный выигрыш: {int(10 * coef)} баллов")
    else:
        await callback.answer("⚠️ Ты уже делал прогноз!", show_alert=True)

@dp.message_handler(Text(equals="🏆 Мой рейтинг"))
async def my_rating(message: types.Message):
    points = get_user_points(message.from_user.id)
    await message.answer(f"📊 *Твой счёт: {points} баллов*", parse_mode="Markdown")

@dp.message_handler(Text(equals="📊 Таблица лидеров"))
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
        "Пример: `Победа А:3.5, Ничья:3.0, Победа Б:3.2`\n\n"
        "Если коэффициент не указать, будет 1.0",
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
        f"📊 Варианты: {', '.join([f'{k} (x{v})' for k,v in options.items()])}\n\n"
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
        await message.answer("📝 Использование: `/finish ID Победитель`\nПример: `/finish 1 Победа А`", parse_mode="Markdown")
        return
    _, event_id_str, winner = parts
    event_id = int(event_id_str)
    event = get_event(event_id)
    if not event:
        await message.answer(f"❌ Событие с ID {event_id} не найдено!")
        return
    if event[4] != 'active':
        await message.answer(f"⚠️ Событие *{event[1]}* уже завершено!", parse_mode="Markdown")
        return
    winners_count, points = finish_event(event_id, winner)
    await message.answer(
        f"✅ *Событие завершено!*\n\n"
        f"📋 {event[1]}\n"
        f"🏆 Победитель: *{winner}*\n"
        f"💰 Начислено: *{points} баллов* ({winners_count} чел.)",
        parse_mode="Markdown"
    )

if __name__ == "__main__":
    print("🚀 Бот спортивных прогнозов запущен!")
    print("👑 Админ: /add_event, /finish")
    executor.start_polling(dp, skip_updates=True)
