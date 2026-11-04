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
        
        # Gather active positions telemetry for live UI rendering
        positions_list = []
        for sym, p in bot_instance.engine.positions.items():
            cur_p = bot_instance.latest_prices.get(sym, p["entry_price"])
            side = p["side"]
            entry = p["entry_price"]
            leveraged_size = p["leveraged_size"]
            
            if side == "LONG":
                unrealized_pnl = (cur_p - entry) / entry * leveraged_size
                roe_pct = ((cur_p - entry) / entry) * bot_instance.engine.leverage * 100.0
            else:
                unrealized_pnl = (entry - cur_p) / entry * leveraged_size
                roe_pct = ((entry - cur_p) / entry) * bot_instance.engine.leverage * 100.0

            positions_list.append({
                "symbol": sym,
                "side": side,
                "entry_price": entry,
                "current_price": cur_p,
                "margin": p["margin"],
                "unrealized_pnl": round(unrealized_pnl, 2),
                "roe_pct": round(roe_pct, 2),
                "be_active": p.get("partial_tp_done", False),
                "sl_price": p["sl_price"],
                "tp_price": p["tp_price"]
            })

        open_count = len(bot_instance.engine.positions)

        return {
            "starting_capital": starting_capital,
            "total_equity": total_equity,
            "available_cash": available_cash,
            "realized_pnl": realized_pnl,
            "active_positions_count": open_count,
            "leverage": getattr(config, "LEVERAGE", 10),
            "max_concurrent": getattr(config, "MAX_CONCURRENT_TRADES", 5),
            "positions": positions_list
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


CYBERPUNK_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Institutional Quant Terminal — Autonomous 10x Futures</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-color: #030712;
            --panel-bg: #0b0f19;
            --border-color: #1e293b;
            --accent-cyan: #06b6d4;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --text-main: #f8fafc;
            --text-muted: #64748b;
        }
        body { background-color: var(--bg-color); color: var(--text-main); font-family: 'Inter', system-ui, sans-serif; margin: 0; padding: 24px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 1px solid var(--border-color); padding-bottom: 16px; }
        .title { font-size: 24px; font-weight: 800; background: linear-gradient(90deg, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .badge { background: rgba(16, 185, 129, 0.1); color: var(--accent-green); border: 1px solid rgba(16, 185, 129, 0.3); padding: 6px 14px; border-radius: 999px; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; box-shadow: 0 0 15px rgba(16, 185, 129, 0.2); }
        
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .card { background: var(--panel-bg); border: 1px solid var(--border-color); border-radius: 14px; padding: 20px; position: relative; overflow: hidden; }
        .card::before { content: ''; position: absolute; top: 0; left: 0; width: 4px; height: 100%; background: var(--accent-cyan); }
        .card-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; font-weight: 600; }
        .card-val { font-size: 28px; font-weight: 800; color: var(--text-main); }
        
        .panel { background: var(--panel-bg); border: 1px solid var(--border-color); border-radius: 14px; padding: 20px; margin-bottom: 24px; }
        .panel-title { font-size: 13px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 16px; font-weight: 700; letter-spacing: 0.05em; display: flex; justify-content: space-between; align-items: center; }
        
        .positions-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
        .pos-card { background: #0f172a; border: 1px solid #334155; border-radius: 10px; padding: 16px; position: relative; }
        .pos-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; font-weight: 700; font-size: 15px; }
        .pos-row { display: flex; justify-content: space-between; font-size: 13px; color: #94a3b8; margin-bottom: 6px; }
        .pos-val { color: #f1f5f9; font-weight: 600; }
        
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; padding: 12px; color: var(--text-muted); border-bottom: 1px solid var(--border-color); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
        td { padding: 12px; border-bottom: 1px solid #111827; }
        
        .status-open { color: var(--accent-cyan); font-weight: 700; }
        .status-closed { color: var(--text-muted); }
        .pos-pnl { color: var(--accent-green); font-weight: 700; }
        .neg-pnl { color: var(--accent-red); font-weight: 700; }
        .tag-long { background: rgba(16, 185, 129, 0.15); color: var(--accent-green); padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
        .tag-short { background: rgba(239, 68, 68, 0.15); color: var(--accent-red); padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
        .shield-badge { background: #1e3a8a; color: #93c5fd; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">⚡ QUANT TERMINAL // Institutional Futures Engine</div>
        <div class="badge" id="live-badge">● LIVE WSS STREAM (50 COINS)</div>
    </div>
    
    <div class="grid">
        <div class="card">
            <div class="card-label">Total Portfolio Equity</div>
            <div class="card-val" id="total-equity">$1,000.00</div>
        </div>
        <div class="card" style="--accent-cyan: #38bdf8;">
            <div class="card-label">Available Wallet Cash</div>
            <div class="card-val" id="avail-cash">$1,000.00</div>
        </div>
        <div class="card" style="--accent-cyan: #10b981;">
            <div class="card-label">Realized Net PnL</div>
            <div class="card-val" id="realized-pnl">$0.00</div>
        </div>
        <div class="card" style="--accent-cyan: #818cf8;">
            <div class="card-label">Active Futures Slots</div>
            <div class="card-val" id="active-slots">0 / 5</div>
        </div>
    </div>

    <div class="panel">
        <div class="panel-title">Active Live Positions & Floating ROE%</div>
        <div class="positions-grid" id="active-positions-container">
            <div style="color: var(--text-muted); font-size: 13px; font-style: italic;">No active positions open right now...</div>
        </div>
    </div>

    <div class="panel">
        <div class="panel-title">Real-Time Portfolio Equity Curve (USD)</div>
        <canvas id="equityChart" height="70"></canvas>
    </div>

    <div class="panel">
        <div class="panel-title">Recent Trade & Scale-Out Activity Log</div>
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
        const equityData = { labels: [], datasets: [{ label: 'Portfolio Equity ($)', data: [], borderColor: '#06b6d4', backgroundColor: 'rgba(6, 182, 212, 0.08)', borderWidth: 2, fill: true, tension: 0.35 }] };
        const chart = new Chart(ctx, { type: 'line', data: equityData, options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#64748b', font: { size: 11 } }, grid: { color: '#1e293b' } }, y: { ticks: { color: '#64748b', font: { size: 11 } }, grid: { color: '#1e293b' } } } } });

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

                    // Render Active Positions Cards
                    const posContainer = document.getElementById('active-positions-container');
                    if (m.positions && m.positions.length > 0) {
                        posContainer.innerHTML = '';
                        m.positions.forEach(p => {
                            const isLong = p.side === 'LONG';
                            const pnlClass = p.unrealized_pnl >= 0 ? 'pos-pnl' : 'neg-pnl';
                            const shieldHtml = p.be_active ? ' <span class="shield-badge">BREAK-EVEN SHIELD 🛡️</span>' : '';
                            
                            const div = document.createElement('div');
                            div.className = 'pos-card';
                            div.innerHTML = `
                                <div class="pos-header">
                                    <span>${p.symbol} <span class="${isLong ? 'tag-long' : 'tag-short'}">${p.side} 10x</span>${shieldHtml}</span>
                                    <span class="${pnlClass}">${p.unrealized_pnl >= 0 ? '+' : ''}$${p.unrealized_pnl.toFixed(2)} (${p.roe_pct >= 0 ? '+' : ''}${p.roe_pct.toFixed(1)}%)</span>
                                </div>
                                <div class="pos-row"><span>Entry Price:</span><span class="pos-val">$${p.entry_price.toFixed(5)}</span></div>
                                <div class="pos-row"><span>Live WSS Price:</span><span class="pos-val" style="color: #38bdf8;">$${p.current_price.toFixed(5)}</span></div>
                                <div class="pos-row"><span>Active Margin:</span><span class="pos-val">$${p.margin.toFixed(2)}</span></div>
                                <div class="pos-row"><span>Stop-Loss:</span><span class="pos-val">$${p.sl_price.toFixed(5)}</span></div>
                            `;
                            posContainer.appendChild(div);
                        });
                    } else {
                        posContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 13px; font-style: italic;">No active positions open right now...</div>';
                    }

                    // Update Chart
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
        setInterval(refreshData, 3000);
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    return CYBERPUNK_DASHBOARD_HTML
