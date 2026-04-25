import os
import json
import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Функция для получения БД с созданием таблиц
def get_db():
    conn = sqlite3.connect("sports_bot.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Создаём таблицы, если их нет
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            options TEXT,
            status TEXT DEFAULT 'active',
            winner TEXT,
            created_at TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_id INTEGER,
            selected_option TEXT,
            bet_time TIMESTAMP,
            is_win BOOLEAN DEFAULT 0,
            points_earned INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            points INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    return conn

@app.get("/miniapp", response_class=HTMLResponse)
async def miniapp(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/events")
async def get_events():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, description, options FROM events WHERE status = 'active' ORDER BY id DESC")
        rows = cursor.fetchall()
        events = []
        for row in rows:
            events.append({
                "id": row[0],
                "title": row[1],
                "description": row[2],
                "options": json.loads(row[3])
            })
        conn.close()
        return JSONResponse(content={"events": events})
    except Exception as e:
        return JSONResponse(content={"events": [], "error": str(e)})

@app.get("/api/leaders")
async def get_leaders():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT full_name, username, points FROM users ORDER BY points DESC LIMIT 10")
        rows = cursor.fetchall()
        leaders = []
        for i, row in enumerate(rows):
            name = row[0] or row[1] or f"Player_{i+1}"
            leaders.append({"name": name, "points": row[2]})
        conn.close()
        return JSONResponse(content={"leaders": leaders})
    except Exception as e:
        return JSONResponse(content={"leaders": [], "error": str(e)})

@app.get("/api/user/{user_id}/points")
async def get_user_points(user_id: int):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        points = row[0] if row else 0
        return JSONResponse(content={"points": points})
    except Exception as e:
        return JSONResponse(content={"points": 0, "error": str(e)})

@app.post("/api/bet")
async def place_bet(request: Request):
    try:
        data = await request.json()
        user_id = data.get("user_id")
        event_id = data.get("event_id")
        option = data.get("option")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Проверка, не делал ли уже прогноз
        cursor.execute("SELECT id FROM bets WHERE user_id = ? AND event_id = ?", (user_id, event_id))
        if cursor.fetchone():
            conn.close()
            return JSONResponse(content={"success": False, "error": "Вы уже делали прогноз!"})
        
        # Сохраняем прогноз
        cursor.execute(
            "INSERT INTO bets (user_id, event_id, selected_option, bet_time) VALUES (?, ?, ?, ?)",
            (user_id, event_id, option, datetime.now())
        )
        conn.commit()
        conn.close()
        return JSONResponse(content={"success": True})
    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Mini App API запущен на порту {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
