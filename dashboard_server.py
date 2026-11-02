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
    """Ensure database tables exist on startup."""
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
    # Startup: Start trading bot in the background
    bot_task = asyncio.create_task(bot_instance.run_parallel_trading())
    yield
    # Shutdown: Stop bot loop cleanly
    bot_instance.is_running = False
    bot_task.cancel()


app = FastAPI(
    title="Autonomous Crypto Trading Bot Dashboard",
    description="Real-time portfolio metrics, trade journal, and live DexScreener monitor.",
    version="1.1.0",
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
        
        # Aggregate closed trade counts and wins
        cursor.execute("SELECT COUNT(*) as total_trades, SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins FROM trades WHERE status='CLOSED'")
        row = cursor.fetchone()
        total_trades = row["total_trades"] if row and row["total_trades"] else 0
        wins = row["wins"] if row and row["wins"] else 0
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

        # Calculate realized PnL
        cursor.execute("SELECT SUM(pnl) as total_pnl FROM trades WHERE status='CLOSED'")
        pnl_row = cursor.fetchone()
        total_pnl = round(pnl_row["total_pnl"], 2) if pnl_row and pnl_row["total_pnl"] is not None else 0.0
        
        # Calculate active trades count
        cursor.execute("SELECT COUNT(*) as open_trades FROM trades WHERE status='OPEN'")
        open_row = cursor.fetchone()
        open_trades = open_row["open_trades"] if open_row else 0
        
        conn.close()

        # Engine cash or derived balance
        balance = getattr(bot_instance.engine, "cash_balance", 1000.0)

        return {
            "virtual_balance": round(balance, 2),
            "total_pnl": total_pnl,
            "win_rate": round(win_rate, 1),
            "total_trades": total_trades,
            "open_trades": open_trades,
            "bot_status": "ACTIVE" if bot_instance.is_running else "STOPPED"
        }
    except Exception as e:
        return {
            "virtual_balance": 1000.0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "total_trades": 0,
            "open_trades": 0,
            "bot_status": "STARTING",
            "info": str(e)
        }


@app.get("/api/trades", response_class=JSONResponse)
async def get_trades() -> List[Dict[str, Any]]:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 30")
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
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b1120; color: #f8fafc; margin: 0; padding: 24px; }
            .container { max-width: 1150px; margin: auto; }
            .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1e293b; padding-bottom: 16px; margin-bottom: 24px; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
            .card { background: #131d31; padding: 20px; border-radius: 12px; border: 1px solid #1e293b; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2); }
            .card h3 { margin: 0 0 8px 0; color: #94a3b8; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; }
            .card .value { font-size: 1.75rem; font-weight: 700; }
            .chart-box { background: #131d31; padding: 20px; border-radius: 12px; border: 1px solid #1e293b; margin-bottom: 24px; }
            table { width: 100%; border-collapse: collapse; background: #131d31; border-radius: 12px; overflow: hidden; border: 1px solid #1e293b; }
            th, td { padding: 14px 18px; text-align: left; border-bottom: 1px solid #1e293b; font-size: 0.88rem; }
            th { background: #0d1527; color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 0.78rem; letter-spacing: 0.05em; }
            .profit { color: #22c55e; font-weight: 600; }
            .loss { color: #ef4444; font-weight: 600; }
            .status-badge { display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }
            .badge-open { background: #0284c725; color: #38bdf8; border: 1px solid #0284c750; }
            .badge-closed { background: #33415550; color: #cbd5e1; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div>
                    <h1 style="margin: 0; font-size: 1.6rem; font-weight: 700;">Autonomous Trading Bot Monitor</h1>
                    <small style="color: #64748b;">Cloud Deployment • Real DEX Pairs (SOL, BONK, JUP)</small>
                </div>
                <div id="status" style="background: #22c55e20; color: #22c55e; border: 1px solid #22c55e50; padding: 6px 14px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;">ONLINE</div>
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
                    <h3>Closed Trades</h3>
                    <div class="value" id="trades">0</div>
                </div>
            </div>

            <div class="chart-box">
                <h3 style="margin-top: 0; color: #94a3b8; font-size: 0.9rem; text-transform: uppercase;">Portfolio Trajectory</h3>
                <canvas id="portfolioChart" height="80"></canvas>
            </div>

            <h3 style="color: #94a3b8; font-size: 0.9rem; text-transform: uppercase; margin-bottom: 12px;">Recent Trade Activity</h3>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Token</th>
                        <th>Action</th>
                        <th>Entry Price</th>
                        <th>Exit Price</th>
                        <th>PnL</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody id="trade-log">
                    <tr><td colspan="7" style="text-align:center; color: #64748b;">Awaiting trade updates...</td></tr>
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
                        backgroundColor: 'rgba(56, 189, 248, 0.08)',
                        borderWidth: 2,
                        tension: 0.25,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: { grid: { color: '#1e293b' } },
                        x: { grid: { color: '#1e293b' } }
                    }
                }
            });

            function formatPrice(val) {
                if (!val || isNaN(val)) return '-';
                const num = Number(val);
                return num < 0.01 ? '$' + num.toFixed(6) : '$' + num.toFixed(4);
            }

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
                        tbody.innerHTML = trades.map(t => {
                            const pnlVal = t.pnl || 0;
                            const isWin = pnlVal >= 0;
                            const statusClass = t.status === 'OPEN' ? 'badge-open' : 'badge-closed';
                            return `
                                <tr>
                                    <td>${t.timestamp || '-'}</td>
                                    <td><strong>${t.token_symbol}</strong></td>
                                    <td>${t.action}</td>
                                    <td>${formatPrice(t.entry_price)}</td>
                                    <td>${formatPrice(t.exit_price)}</td>
                                    <td class="${isWin ? 'profit' : 'loss'}">${t.status === 'CLOSED' ? (isWin ? '+' : '') + Number(pnlVal).toFixed(2) : '$0.00'}</td>
                                    <td><span class="status-badge ${statusClass}">${t.status}</span></td>
                                </tr>
                            `;
                        }).join('');
                    }
                } catch(e) {
                    console.error("Dashboard refresh error:", e);
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
