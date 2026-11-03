import os
import sqlite3
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from multi_token_bot import MultiTokenBot
import asyncio

app = FastAPI(title="Autonomous Trading Bot Monitor")

DB_PATH = os.environ.get("TRADING_BOT_DB", "trading_bot.db")
bot_instance = MultiTokenBot()

@app.on_event("startup")
async def startup_event():
    # Start bot background task
    asyncio.create_task(bot_instance.run_parallel_trading())

@app.get("/healthz")
async def health_check():
    return {"status": "ok", "engine": "running"}

@app.get("/api/metrics")
async def get_metrics():
    engine = bot_instance.engine
    
    # Calculate Total Portfolio Equity
    locked_margin = sum(p.get("margin", 0.0) for p in engine.positions.values())
    total_equity = engine.cash_balance + locked_margin

    # Calculate Win Rate & Total Closed Trades from DB
    win_rate = 0.0
    closed_count = 0
    total_realized_pnl = engine.realized_pnl

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT pnl FROM trades WHERE status = 'CLOSED'")
        rows = cursor.fetchall()
        conn.close()

        closed_count = len(rows)
        if closed_count > 0:
            wins = sum(1 for r in rows if r[0] > 0)
            win_rate = round((wins / closed_count) * 100, 1)
            total_realized_pnl = sum(r[0] for r in rows)
    except Exception as e:
        print(f"[DB Metric Error]: {e}")

    return {
        "available_cash": round(engine.cash_balance, 2),
        "locked_margin": round(locked_margin, 2),
        "total_equity": round(total_equity, 2),
        "realized_pnl": round(total_realized_pnl, 2),
        "win_rate": win_rate,
        "closed_trades": closed_count,
        "active_slots": f"{len(engine.positions)}/{engine.max_concurrent}"
    }

@app.get("/api/trades")
async def get_trades():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, token_symbol, action, amount, entry_price, exit_price, pnl, status 
            FROM trades ORDER BY id DESC LIMIT 15
        """)
        rows = cursor.fetchall()
        conn.close()

        trades = []
        for r in rows:
            trades.append({
                "id": r[0],
                "time": r[1],
                "token": r[2],
                "action": r[3],
                "amount": r[4],
                "entry_price": r[5],
                "exit_price": r[6],
                "pnl": r[7],
                "status": r[8]
            })
        return trades
    except Exception as e:
        return []

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)
