import os
import sqlite3
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any, List
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from multi_token_bot import MultiTokenBot

DB_PATH = os.environ.get("TRADING_BOT_DB", "trading_bot.db")
bot_instance = MultiTokenBot()


def init_db():
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


init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: launch bot loop inside background task
    bot_task = asyncio.create_task(bot_instance.run_parallel_trading())
    yield
    # Shutdown: stop bot cleanly
    bot_instance.is_running = False
    bot_task.cancel()


app = FastAPI(
    title="Autonomous Crypto Trading Bot Dashboard",
    description="Real-time performance, trade logs, and metrics.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/healthz")
@app.head("/healthz")
async def health_check():
    return {"status": "ok", "environment": "render"}


@app.get("/api/metrics", response_class=JSONResponse)
async def get_metrics() -> Dict[str, Any]:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total_trades, SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins FROM trades WHERE status='CLOSED'")
        row = cursor.fetchone()
        total_trades = row["total_trades"] if row and row["total_trades"] else 0
        wins = row["wins"] if row and row["wins"] else 0
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

        cursor.execute("SELECT SUM(pnl) as total_pnl FROM trades WHERE status='CLOSED'")
        pnl_row = cursor.fetchone()
        total_pnl = round(pnl_row["total_pnl"], 2) if pnl_row and pnl_row["total_pnl"] is not None else 0.0
        conn.close()

        return {
            "virtual_balance": round(1000.0 + total_pnl, 2),
            "total_pnl": total_pnl,
            "win_rate": round(win_rate, 2),
            "total_trades": total_trades,
            "bot_status": "ACTIVE" if bot_instance.is_running else "STOPPED"
        }
    except Exception as e:
        return {
            "virtual_balance": 1000.0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "total_trades": 0,
            "bot_status": "STARTING",
            "info": str(e)
        }


@app.get("/api/trades", response_class=JSONResponse)
async def get_trades() -> List[Dict[str, Any]]:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 20")
        rows = cursor.fetchall()
        trades = [dict(ix) for ix in rows]
        conn.close()
        return trades
    except Exception:
        return []


@app.get("/", response_class=HTMLResponse)
@app.head("/")
async def serve_dashboard():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Autonomous Crypto Bot Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
            .container { max-width: 1100px; margin: auto; }
            .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 16px; margin-bottom: 24px; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
            .card { background: #1e293b; padding: 20px; border-radius: 10px; border: 1px solid #334155; }
            .card h3 { margin: 0 0 10px 0; color: #94a3b8; font-size: 0.9rem; text-transform: uppercase; }
            .card .value { font-size: 1.8rem; font-weight: bold; }
            .chart-box { background: #1e293b; padding: 20px; border-radius: 10px; border: 1px solid #334155; margin-bottom: 24px; }
            table { width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 10px; overflow: hidden; border: 1px solid #334155; }
            th, td { padding: 12px 16px; text-align: left; border-bottom: 1px solid #334155; font-size: 0.9rem; }
            th { background: #0f172a; color: #94a3b8; }
            .profit { color: #22c55e; }
            .loss { color: #ef4444; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div>
                    <h1 style="margin: 0; font-size: 1.5rem;">Autonomous Trading Bot Monitor</h1>
                    <small style="color: #64748b;">Cloud VPS Deployment (Render)</small>
                </div>
                <div id="status" style="background: #22c55e20; color: #22c55e; padding: 6px 12px; border-radius: 20px; font-weight: bold; font-size: 0.85rem;">ONLINE</div>
            </div>

            <div class="grid">
                <div class="card">
                    <h3>Virtual Balance</h3>
                    <div class="value" id="balance">$1,000.00</div>
                </div>
                <div class="card">
                    <h3>Total PnL</h3>
                    <div class="value" id="pnl">$0.00</div>
                </div>
                <div class="card">
                    <h3>Win Rate</h3>
                    <div class="value" id="winrate">0.0%</div>
                </div>
                <div class="card">
                    <h3>Total Trades</h3>
                    <div class="value" id="trades">0</div>
                </div>
            </div>

            <div class="chart-box">
                <h3 style="margin-top: 0; color: #94a3b8;">Portfolio Trajectory</h3>
                <canvas id="portfolioChart" height="90"></canvas>
            </div>

            <h3 style="color: #94a3b8;">Recent Trade Activity</h3>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Token</th>
                        <th>Action</th>
                        <th>Entry</th>
                        <th>Exit</th>
                        <th>PnL</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody id="trade-log">
                    <tr><td colspan="7" style="text-align:center; color: #64748b;">Waiting for trade signals...</td></tr>
                </tbody>
            </table>
        </div>

        <script>
            const ctx = document.getElementById('portfolioChart').getContext('2d');
            const chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: ['Start', 'Current'],
                    datasets: [{
                        label: 'Portfolio Value ($)',
                        data: [1000, 1000],
                        borderColor: '#38bdf8',
                        tension: 0.3,
                        fill: false
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: { grid: { color: '#334155' } },
                        x: { grid: { color: '#334155' } }
                    }
                }
            });

            async function updateDashboard() {
                try {
                    const metricsRes = await fetch('/api/metrics');
                    const metrics = await metricsRes.json();
                    
                    document.getElementById('balance').innerText = '$' + Number(metrics.virtual_balance).toFixed(2);
                    const pnlElem = document.getElementById('pnl');
                    pnlElem.innerText = (metrics.total_pnl >= 0 ? '+$' : '-$') + Math.abs(metrics.total_pnl).toFixed(2);
                    pnlElem.className = 'value ' + (metrics.total_pnl >= 0 ? 'profit' : 'loss');
                    document.getElementById('winrate').innerText = Number(metrics.win_rate).toFixed(1) + '%';
                    document.getElementById('trades').innerText = metrics.total_trades;

                    const tradesRes = await fetch('/api/trades');
                    const trades = await tradesRes.json();
                    const tbody = document.getElementById('trade-log');
                    
                    if (trades && trades.length > 0) {
                        tbody.innerHTML = trades.map(t => `
                            <tr>
                                <td>${t.timestamp || '-'}</td>
                                <td><strong>${t.token_symbol}</strong></td>
                                <td>${t.action}</td>
                                <td>$${t.entry_price ? Number(t.entry_price).toFixed(4) : '0.00'}</td>
                                <td>$${t.exit_price ? Number(t.exit_price).toFixed(4) : '-'}</td>
                                <td class="${(t.pnl || 0) >= 0 ? 'profit' : 'loss'}">${(t.pnl || 0) >= 0 ? '+' : ''}${(t.pnl || 0).toFixed(2)}</td>
                                <td>${t.status}</td>
                            </tr>
                        `).join('');
                    }
                } catch(e) {
                    console.error("Dashboard fetch error:", e);
                }
            }

            setInterval(updateDashboard, 5000);
            updateDashboard();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("dashboard_server:app", host="0.0.0.0", port=port, reload=False)
