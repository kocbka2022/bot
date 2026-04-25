import os
import json
import sqlite3
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

# База данных
db_conn = sqlite3.connect("sports_bot.db", check_same_thread=False)
cursor = db_conn.cursor()

# Создаём приложение FastAPI
app = FastAPI()

# Подключаем шаблоны
templates = Jinja2Templates(directory="templates")

@app.get("/miniapp", response_class=HTMLResponse)
async def miniapp(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/events")
async def get_events():
    cursor.execute("SELECT id, title, description, options FROM events WHERE status = 'active'")
    events = cursor.fetchall()
    return {
        "events": [
            {"id": e[0], "title": e[1], "description": e[2], "options": json.loads(e[3])}
            for e in events
        ]
    }

@app.get("/api/leaders")
async def get_leaders():
    cursor.execute("SELECT full_name, username, points FROM users ORDER BY points DESC LIMIT 10")
    leaders = []
    for i, row in enumerate(cursor.fetchall()):
        name = row[0] or row[1] or f"User_{i}"
        leaders.append({"name": name, "points": row[2]})
    return {"leaders": leaders}

@app.get("/api/user/{user_id}/points")
async def get_user_points(user_id: int):
    cursor.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    return {"points": res[0] if res else 0}

@app.post("/api/bet")
async def place_bet(request: Request):
    data = await request.json()
    user_id = data.get("user_id")
    event_id = data.get("event_id")
    option = data.get("option")
    
    # Проверка, не делал ли уже прогноз
    cursor.execute("SELECT id FROM bets WHERE user_id = ? AND event_id = ?", (user_id, event_id))
    if cursor.fetchone():
        return {"success": False, "error": "Вы уже делали прогноз!"}
    
    cursor.execute(
        "INSERT INTO bets (user_id, event_id, selected_option, bet_time) VALUES (?, ?, ?, ?)",
        (user_id, event_id, option, datetime.now())
    )
    db_conn.commit()
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
