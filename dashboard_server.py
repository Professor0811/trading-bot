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

bot_instance = MultiTokenBot()


def init_db():
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


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Autonomous 10x Futures Quant Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background-color: #0b0e14; color: #e2e8f0; font-family: 'Segoe UI', Roboto, Helvetica, sans-serif; margin: 0; padding: 24px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 1px solid #1e293b; padding-bottom: 16px; }
        .title { font-size: 22px; font-weight: 700; color: #38bdf8; }
        .badge { background: #064e3b; color: #34d399; padding: 6px 12px; border-radius: 999px; font-size: 13px; font-weight: 600; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .card { background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 18px; }
        .card-label { font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }
        .card-val { font-size: 26px; font-weight: 700; color: #f8fafc; }
        .panel { background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 20px; margin-bottom: 24px; }
        .panel-title { font-size: 14px; color: #94a3b8; text-transform: uppercase; margin-bottom: 16px; font-weight: 600; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th { text-align: left; padding: 12px; color: #64748b; border-bottom: 1px solid #1f2937; font-size: 12px; text-transform: uppercase; }
        td { padding: 12px; border-bottom: 1px solid #1e293b; }
        .status-open { color: #38bdf8; font-weight: 700; }
        .status-closed { color: #94a3b8; }
        .pos-pnl { color: #34d399; font-weight: 700; }
        .neg-pnl { color: #f87171; font-weight: 700; }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">⚡ Autonomous 10x Futures Bot — MTF + Volume + Scale-Out Engine</div>
        <div class="badge" id="live-badge">● LIVE WSS STREAM</div>
    </div>
    <div class="grid">
        <div class="card">
            <div class="card-label">Total Portfolio Equity</div>
            <div class="card-val" id="total-equity">$1,000.00</div>
        </div>
        <div class="card">
            <div class="card-label">Available Wallet Cash</div>
            <div class="card-val" id="avail-cash">$1,000.00</div>
        </div>
        <div class="card">
            <div class="card-label">Realized Net PnL</div>
            <div class="card-val" id="realized-pnl">$0.00</div>
        </div>
        <div class="card">
            <div class="card-label">Active Futures Slots</div>
            <div class="card-val" id="active-slots">0 / 5</div>
        </div>
    </div>
    <div class="panel">
        <div class="panel-title">Real-Time Portfolio Equity Curve (USD)</div>
        <canvas id="equityChart" height="75"></canvas>
    </div>
    <div class="panel">
        <div class="panel-title">Recent Trade & Scale-Out Activity</div>
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Token</th>
                    <th>Action</th>
                    <th>Entry Price</th>
                    <th>Exit Price</th>
                    <th>Realized PnL</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody id="trades-body"></tbody>
        </table>
    </div>
    <script>
        const ctx = document.getElementById('equityChart').getContext('2d');
        const equityData = { labels: [], datasets: [{ label: 'Portfolio Equity ($)', data: [], borderColor: '#38bdf8', backgroundColor: 'rgba(56, 189, 248, 0.1)', fill: true, tension: 0.3 }] };
        const chart = new Chart(ctx, { type: 'line', data: equityData, options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#64748b' } }, y: { ticks: { color: '#64748b' } } } } });

        async function refreshData() {
            try {
                const mRes = await fetch('/api/metrics');
                const m = await mRes.json();
                if (m.total_equity !== undefined) {
                    document.getElementById('total-equity').textContent = '$' + m.total_equity.toFixed(2);
                    document.getElementById('avail-cash').textContent = '$' + m.available_cash.toFixed(2);
                    const pnlEl = document.getElementById('realized-pnl');
                    pnlEl.textContent = (m.realized_pnl >= 0 ? '+$' : '-$') + Math.abs(m.realized_pnl).toFixed(2);
                    pnlEl.className = 'card-val ' + (m.realized_pnl >= 0 ? 'pos-pnl' : 'neg-pnl');
                    document.getElementById('active-slots').textContent = m.active_positions_count + ' / ' + m.max_concurrent;

                    const nowStr = new Date().toLocaleTimeString();
                    if (equityData.labels.length > 30) { equityData.labels.shift(); equityData.datasets[0].data.shift(); }
                    equityData.labels.push(nowStr);
                    equityData.datasets[0].data.push(m.total_equity);
                    chart.update();
                }

                const tRes = await fetch('/api/trades');
                const trades = await tRes.json();
                const tbody = document.getElementById('trades-body');
                tbody.innerHTML = '';
                trades.forEach(t => {
                    const tr = document.createElement('tr');
                    const pnlVal = t.pnl ? parseFloat(t.pnl) : 0;
                    const pnlStr = t.status === 'CLOSED' ? ((pnlVal >= 0 ? '+$' : '-$') + Math.abs(pnlVal).toFixed(2)) : '-';
                    const pnlCls = t.status === 'CLOSED' ? (pnlVal >= 0 ? 'pos-pnl' : 'neg-pnl') : '';
                    tr.innerHTML = `
                        <td>${t.timestamp || '-'}</td>
                        <td><b>${t.token_symbol}</b></td>
                        <td>${t.action}</td>
                        <td>$${parseFloat(t.entry_price || 0).toFixed(5)}</td>
                        <td>${t.exit_price ? '$' + parseFloat(t.exit_price).toFixed(5) : '-'}</td>
                        <td class="${pnlCls}">${pnlStr}</td>
                        <td class="${t.status === 'OPEN' ? 'status-open' : 'status-closed'}">${t.status}</td>
                    `;
                    tbody.appendChild(tr);
                });
            } catch (e) { console.error(e); }
        }
        refreshData();
        setInterval(refreshData, 4000);
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    return DASHBOARD_HTML
