import os
import asyncio
import sqlite3
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import config
from multi_token_bot import MultiTokenBot

DB_PATH = os.environ.get("TRADING_BOT_DB", "trading_bot.db")

# Create a global bot instance so both background loop and API can read live state
bot_instance = MultiTokenBot()


def init_db():
    """Ensure SQLite trades table exists on startup."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                token_symbol TEXT,
                action TEXT,
                amount REAL,
                entry_price REAL,
                exit_price REAL,
                pnl REAL,
                status TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print("[DB Init Error]:", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Automatically launches the MultiTokenBot in the background when FastAPI starts."""
    init_db()
    print("[Dashboard Server] Launching MultiTokenBot background engine...")
    bot_task = asyncio.create_task(bot_instance.run_parallel_trading())
    yield
    bot_instance.is_running = False
    bot_task.cancel()


app = FastAPI(title="10x Autonomous Futures Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.api_route("/healthz", methods=["GET", "HEAD"])
async def health_check():
    """Support both GET and HEAD for UptimeRobot monitoring."""
    return JSONResponse(status_code=200, content={"status": "healthy"})


@app.get("/api/metrics")
async def get_metrics():
    try:
        starting_capital = getattr(config, "STARTING_CAPITAL", 1000.0)
        realized_pnl = round(bot_instance.engine.realized_pnl, 2)
        available_cash = round(bot_instance.engine.cash_balance, 2)
        total_equity = round(bot_instance.engine.get_total_equity(), 2)
        open_count = len(bot_instance.engine.positions)

        return {
            "starting_capital": starting_capital,
            "total_equity": total_equity,
            "available_cash": available_cash,
            "realized_pnl": realized_pnl,
            "active_positions_count": open_count,
            "leverage": getattr(config, "LEVERAGE", 10),
            "max_concurrent": getattr(config, "MAX_CONCURRENT_TRADES", 5)
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/trades")
async def get_trades():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, token_symbol, action, amount, entry_price, exit_price, pnl, status
            FROM trades
            ORDER BY id DESC
            LIMIT 50
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(ix) for ix in rows]
    except Exception as e:
        return {"error": str(e)}


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_file = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.exists(html_file):
        with open(html_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Futures Trading Dashboard Online</h1>"
