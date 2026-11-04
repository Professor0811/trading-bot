import os
import sqlite3
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import config
from multi_token_bot import MultiTokenBot

DB_PATH = os.environ.get("TRADING_BOT_DB", "trading_bot.db")

app = FastAPI(title="10x Autonomous Futures Dashboard")

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
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(pnl) FROM trades WHERE status = 'CLOSED'")
        row = cursor.fetchone()
        realized_pnl = float(row[0]) if row and row[0] is not None else 0.0

        cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
        open_count = cursor.fetchone()[0]
        conn.close()

        starting_capital = getattr(config, "STARTING_CAPITAL", 1000.0)
        # Margin per slot is 2% of capital ($20 per position)
        margin_per_slot = starting_capital * getattr(config, "POSITION_MARGIN_PERCENT", 0.02)
        locked_margin = open_count * margin_per_slot
        current_equity = starting_capital + realized_pnl
        available_cash = max(0.0, current_equity - locked_margin)

        return {
            "starting_capital": starting_capital,
            "total_equity": round(current_equity, 2),
            "available_cash": round(available_cash, 2),
            "realized_pnl": round(realized_pnl, 2),
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
    # Serve the trading dashboard frontend
    html_file = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.exists(html_file):
        with open(html_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Futures Trading Dashboard Online</h1>"
