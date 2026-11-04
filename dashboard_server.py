import os
import asyncio
import sqlite3
from contextlib import asynccontextmanager
from fastapi import FastAPI, Body
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
        
        positions_list = []
        long_count = 0
        short_count = 0

        for sym, p in bot_instance.engine.positions.items():
            cur_p = bot_instance.latest_prices.get(sym, p["entry_price"])
            side = p["side"]
            entry = p["entry_price"]
            leveraged_size = p["leveraged_size"]
            tp = p["tp_price"]
            sl = p["sl_price"]
            partial_tp = p.get("partial_tp_price", tp)

            if side == "LONG":
                long_count += 1
                unrealized_pnl = (cur_p - entry) / entry * leveraged_size
                roe_pct = ((cur_p - entry) / entry) * bot_instance.engine.leverage * 100.0
                total_dist = max(0.0001, tp - entry)
                current_dist = max(0.0, cur_p - entry)
                progress_pct = min(100.0, (current_dist / total_dist) * 100.0)
            else:
                short_count += 1
                unrealized_pnl = (entry - cur_p) / entry * leveraged_size
                roe_pct = ((entry - cur_p) / entry) * bot_instance.engine.leverage * 100.0
                total_dist = max(0.0001, entry - tp)
                current_dist = max(0.0, entry - cur_p)
                progress_pct = min(100.0, (current_dist / total_dist) * 100.0)

            positions_list.append({
                "symbol": sym,
                "side": side,
                "entry_price": entry,
                "current_price": cur_p,
                "margin": p["margin"],
                "unrealized_pnl": round(unrealized_pnl, 2),
                "roe_pct": round(roe_pct, 2),
                "be_active": p.get("partial_tp_done", False),
                "sl_price": sl,
                "tp_price": tp,
                "partial_tp": partial_tp,
                "progress_pct": round(progress_pct, 1)
            })

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) FROM trades WHERE status = 'CLOSED'")
        row = cursor.fetchone()
        conn.close()
        
        total_closed = row[0] if row and row[0] else 0
        winning_trades = row[1] if row and row[1] else 0
        win_rate = round((winning_trades / total_closed * 100.0), 1) if total_closed > 0 else 0.0

        radar_list = []
        for sym, hist in bot_instance.price_history.items():
            if len(hist) >= 2:
                change = ((hist[-1] - hist[0]) / hist[0]) * 100.0
                radar_list.append({
                    "symbol": sym,
                    "price": hist[-1],
                    "change_pct": round(change, 2)
                })
        radar_list.sort(key=lambda x: abs(x["change_pct"]), reverse=True)

        return {
            "starting_capital": starting_capital,
            "total_equity": total_equity,
            "available_cash": available_cash,
            "realized_pnl": realized_pnl,
            "win_rate": win_rate,
            "total_closed": total_closed,
            "active_positions_count": len(bot_instance.engine.positions),
            "leverage": getattr(config, "LEVERAGE", 10),
            "max_concurrent": getattr(config, "MAX_CONCURRENT_TRADES", 5),
            "trading_enabled": bot_instance.trading_enabled,
            "long_count": long_count,
            "short_count": short_count,
            "positions": positions_list,
            "radar": radar_list[:6]
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


@app.post("/api/control")
async def control_bot(payload: dict = Body(...)):
    action = payload.get("action")
    if action == "pause":
        bot_instance.trading_enabled = False
        return {"status": "paused"}
    elif action == "resume":
        bot_instance.trading_enabled = True
        bot_instance.circuit_breaker_alerted = False
        return {"status": "resumed"}
    elif action == "closeall":
        closed_count = 0
        for sym in list(bot_instance.engine.positions.keys()):
            cur_p = bot_instance.latest_prices.get(sym, bot_instance.engine.positions[sym]["entry_price"])
            bot_instance.engine._close_token_position(sym, "Web Emergency /closeall", cur_p)
            closed_count += 1
        return {"status": "closed_all", "count": closed_count}
    return {"error": "unknown action"}


ULTIMATE_TERMINAL_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Wall Street Quant Terminal // Pro 10x Futures</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-color: #020617;
            --panel-bg: #090d16;
            --border-color: #1e293b;
            --accent-cyan: #06b6d4;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --text-main: #f8fafc;
            --text-muted: #64748b;
        }
        body { background-color: var(--bg-color); color: var(--text-main); font-family: 'Inter', system-ui, sans-serif; margin: 0; padding: 24px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 1px solid var(--border-color); padding-bottom: 16px; flex-wrap: wrap; gap: 12px; }
        .title { font-size: 24px; font-weight: 800; background: linear-gradient(90deg, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        
        .header-actions { display: flex; gap: 10px; align-items: center; }
        .btn { background: #1e293b; color: #f8fafc; border: 1px solid #334155; padding: 8px 16px; border-radius: 8px; font-weight: 700; cursor: pointer; font-size: 12px; transition: all 0.2s; }
        .btn:hover { background: #334155; }
        .btn-pause { background: rgba(239, 68, 68, 0.2); color: #f87171; border-color: rgba(239, 68, 68, 0.4); }
        .btn-resume { background: rgba(16, 185, 129, 0.2); color: #34d399; border-color: rgba(16, 185, 129, 0.4); }
        .btn-close { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border-color: rgba(245, 158, 11, 0.4); }
        
        .badge { background: rgba(16, 185, 129, 0.1); color: var(--accent-green); border: 1px solid rgba(16, 185, 129, 0.3); padding: 6px 14px; border-radius: 999px; font-size: 12px; font-weight: 700; }
        .badge-paused { background: rgba(239, 68, 68, 0.1); color: var(--accent-red); border: 1px solid rgba(239, 68, 68, 0.3); }

        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .card { background: var(--panel-bg); border: 1px solid var(--border-color); border-radius: 14px; padding: 20px; position: relative; overflow: hidden; }
        .card::before { content: ''; position: absolute; top: 0; left: 0; width: 4px; height: 100%; background: var(--accent-cyan); }
        .card-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; font-weight: 600; }
        .card-val { font-size: 26px; font-weight: 800; color: var(--text-main); }

        .dashboard-layout { display: grid; grid-template-columns: 3fr 1fr; gap: 24px; margin-bottom: 24px; }
        @media (max-width: 1024px) { .dashboard-layout { grid-template-columns: 1fr; } }

        .panel { background: var(--panel-bg); border: 1px solid var(--border-color); border-radius: 14px; padding: 20px; margin-bottom: 24px; }
        .panel-title { font-size: 13px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 16px; font-weight: 700; letter-spacing: 0.05em; display: flex; justify-content: space-between; align-items: center; }

        .positions-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
        .pos-card { background: #0f172a; border: 1px solid #334155; border-radius: 10px; padding: 16px; position: relative; }
        .pos-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; font-weight: 700; font-size: 14px; }
        .pos-row { display: flex; justify-content: space-between; font-size: 12px; color: #94a3b8; margin-bottom: 6px; }
        .pos-val { color: #f1f5f9; font-weight: 600; }

        .progress-container { background: #1e293b; border-radius: 999px; height: 8px; width: 100%; margin-top: 12px; overflow: hidden; position: relative; }
        .progress-bar { background: linear-gradient(90deg, #06b6d4, #10b981); height: 100%; border-radius: 999px; transition: width 0.4s ease; }
        .progress-labels { display: flex; justify-content: space-between; font-size: 10px; color: #64748b; margin-top: 4px; }

        .radar-item { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: #0f172a; border-radius: 8px; margin-bottom: 8px; font-size: 13px; border: 1px solid #1e293b; }
        
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
        <div class="title">⚡ WALL STREET QUANT TERMINAL // 10x Futures Pro</div>
        <div class="header-actions">
            <button class="btn btn-pause" onclick="controlBot('pause')">⏸️ Pause Bot</button>
            <button class="btn btn-resume" onclick="controlBot('resume')">▶️ Resume</button>
            <button class="btn btn-close" onclick="controlBot('closeall')">🚨 Close All</button>
            <div class="badge" id="bot-status-badge">● SYSTEM ACTIVE</div>
        </div>
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
            <div class="card-label">Win Rate & Closed</div>
            <div class="card-val" id="win-rate">0.0% (0)</div>
        </div>
        <div class="card" style="--accent-cyan: #f59e0b;">
            <div class="card-label">Directional Exposure</div>
            <div class="card-val" id="exposure-balance">0L / 0S</div>
        </div>
    </div>

    <div class="dashboard-layout">
        <div>
            <div class="panel">
                <div class="panel-title">Active Live Positions & TP Progress Bars</div>
                <div class="positions-grid" id="active-positions-container">
                    <div style="color: var(--text-muted); font-size: 13px; font-style: italic;">No active positions open right now...</div>
                </div>
            </div>

            <div class="panel">
                <div class="panel-title">Real-Time Portfolio Equity Curve (USD)</div>
                <canvas id="equityChart" height="65"></canvas>
            </div>
        </div>

        <div>
            <div class="panel" style="height: 100%;">
                <div class="panel-title">Market Scanner Radar (Top Movers)</div>
                <div id="radar-container">
                    <div style="color: var(--text-muted); font-size: 12px; font-style: italic;">Syncing 50 WSS tokens...</div>
                </div>
            </div>
        </div>
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

        async function controlBot(action) {
            if(!confirm('Are you sure you want to execute action: ' + action.toUpperCase() + '?')) return;
            try {
                const res = await fetch('/api/control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: action })
                });
                const data = await res.json();
                alert('Command executed: ' + JSON.stringify(data));
                refreshData();
            } catch(e) { alert('Error: ' + e); }
        }

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
                    
                    document.getElementById('win-rate').textContent = m.win_rate.toFixed(1) + '% (' + m.total_closed + ')';
                    document.getElementById('exposure-balance').textContent = m.long_count + 'L / ' + m.short_count + 'S';

                    const badge = document.getElementById('bot-status-badge');
                    if (m.trading_enabled) {
                        badge.textContent = '● SYSTEM ACTIVE';
                        badge.className = 'badge';
                    } else {
                        badge.textContent = '⏸️ PAUSED';
                        badge.className = 'badge badge-paused';
                    }

                    const posContainer = document.getElementById('active-positions-container');
                    if (m.positions && m.positions.length > 0) {
                        posContainer.innerHTML = '';
                        m.positions.forEach(p => {
                            const isLong = p.side === 'LONG';
                            const pnlClass = p.unrealized_pnl >= 0 ? 'pos-pnl' : 'neg-pnl';
                            const shieldHtml = p.be_active ? ' <span class="shield-badge">BE SHIELD 🛡️</span>' : '';
                            
                            const div = document.createElement('div');
                            div.className = 'pos-card';
                            div.innerHTML = `
                                <div class="pos-header">
                                    <span>${p.symbol} <span class="${isLong ? 'tag-long' : 'tag-short'}">${p.side} 10x</span>${shieldHtml}</span>
                                    <span class="${pnlClass}">${p.unrealized_pnl >= 0 ? '+' : ''}$${p.unrealized_pnl.toFixed(2)} (${p.roe_pct >= 0 ? '+' : ''}${p.roe_pct.toFixed(1)}%)</span>
                                </div>
                                <div class="pos-row"><span>Entry Price:</span><span class="pos-val">$${p.entry_price.toFixed(5)}</span></div>
                                <div class="pos-row"><span>Live WSS Price:</span><span class="pos-val" style="color: #38bdf8;">$${p.current_price.toFixed(5)}</span></div>
                                <div class="pos-row"><span>Target TP:</span><span class="pos-val">$${p.tp_price.toFixed(5)}</span></div>
                                <div class="progress-container">
                                    <div class="progress-bar" style="width: ${p.progress_pct}%;"></div>
                                </div>
                                <div class="progress-labels"><span>Entry (0%)</span><span>TP Target (${p.progress_pct}%)</span></div>
                            `;
                            posContainer.appendChild(div);
                        });
                    } else {
                        posContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 13px; font-style: italic;">No active positions open right now...</div>';
                    }

                    const radarContainer = document.getElementById('radar-container');
                    if (m.radar && m.radar.length > 0) {
                        radarContainer.innerHTML = '';
                        m.radar.forEach(r => {
                            const col = r.change_pct >= 0 ? '#10b981' : '#ef4444';
                            const item = document.createElement('div');
                            item.className = 'radar-item';
                            item.innerHTML = `
                                <span><b>${r.symbol}</b></span>
                                <span>$${r.price < 1 ? r.price.toFixed(5) : r.price.toFixed(2)}</span>
                                <span style="color: ${col}; font-weight: 700;">${r.change_pct >= 0 ? '+' : ''}${r.change_pct}%</span>
                            `;
                            radarContainer.appendChild(item);
                        });
                    }

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
    return ULTIMATE_TERMINAL_HTML
