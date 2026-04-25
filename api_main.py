import os
import json
import sqlite3
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

app = FastAPI()
templates = Jinja2Templates(directory="templates")

db_conn = sqlite3.connect("sports_bot.db", check_same_thread=False)
cursor = db_conn.cursor()

@app.get("/miniapp", response_class=HTMLResponse)
async def miniapp(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/events")
async def get_events():
    cursor.execute("SELECT id, title, description, options FROM events WHERE status = 'active'")
    events = cursor.fetchall()
    return {"events": [{"id": e[0], "title": e[1], "description": e[2], "options": json.loads(e[3])} for e in events]}

@app.get("/api/leaders")
async def get_leaders():
    cursor.execute("SELECT full_name, username, points FROM users ORDER BY points DESC LIMIT 10")
    leaders = [{"name": row[0] or row[1] or f"User_{i}", "points": row[2]} for i, row in enumerate(cursor.fetchall())]
    return {"leaders": leaders}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))