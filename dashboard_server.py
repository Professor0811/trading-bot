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


app = FastAPI(title="Institutional Quant Terminal", lifespan=lifespan)

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
            liq = p["liq_price"]
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
                "liq_price": liq,
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


VECTOR_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AETHEL // Institutional Quant Terminal</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-base: #0b0f19;
            --panel-bg: #111827;
            --border-line: #1f2937;
            --accent-orange: #f59e0b;
            --accent-cyan: #06b6d4;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }
        body { background-color: var(--bg-base); color: var(--text-main); font-family: 'Inter', system-ui, sans-serif; margin: 0; padding: 24px; }
        
        /* Top Navigation Header */
        .top-nav { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-line); padding-bottom: 16px; margin-bottom: 24px; flex-wrap: wrap; gap: 16px; }
        .brand-box { display: flex; align-items: center; gap: 12px; }
        .brand-logo { width: 36px; height: 36px; background: linear-gradient(135deg, #f59e0b, #d97706); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 18px; color: #fff; box-shadow: 0 0 15px rgba(245,158,11,0.3); }
        .brand-title { font-size: 18px; font-weight: 800; letter-spacing: 0.05em; color: #fff; }
        .brand-sub { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.1em; }
        
        .nav-links { display: flex; gap: 24px; font-size: 13px; font-weight: 600; color: var(--text-muted); }
        .nav-link { cursor: pointer; transition: color 0.2s; }
        .nav-link:hover, .nav-link.active { color: var(--accent-orange); }

        .market-status { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
        .status-pill { background: rgba(16, 185, 129, 0.1); color: var(--accent-green); border: 1px solid rgba(16, 185, 129, 0.3); padding: 5px 12px; border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; }
        .status-pill.paused { background: rgba(239, 68, 68, 0.1); color: var(--accent-red); border-color: rgba(239, 68, 68, 0.3); }

        .btn-group { display: flex; gap: 8px; }
        .btn { background: #1e293b; color: #fff; border: 1px solid #334155; padding: 6px 14px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; transition: all 0.2s; }
        .btn:hover { background: #334155; }
        .btn-orange { background: #d97706; border-color: #f59e0b; color: #fff; }
        .btn-orange:hover { background: #b45309; }

        /* Top Executive Header Cards */
        .exec-header { background: var(--panel-bg); border: 1px solid var(--border-line); border-radius: 12px; padding: 20px; display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 20px; margin-bottom: 24px; align-items: center; }
        @media(max-width: 1024px) { .exec-header { grid-template-columns: 1fr; } }
        .exec-main-val { font-size: 32px; font-weight: 900; color: #fff; margin-top: 4px; }
        .exec-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.1em; font-weight: 700; }
        .exec-sub { font-size: 12px; color: var(--accent-green); font-weight: 600; margin-top: 4px; }
        .exec-stat-box { border-left: 1px solid var(--border-line); padding-left: 20px; }

        /* Metrics Grid */
        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .metric-card { background: var(--panel-bg); border: 1px solid var(--border-line); border-radius: 10px; padding: 16px; }
        .metric-title { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; font-weight: 600; }
        .metric-val { font-size: 22px; font-weight: 800; color: #fff; }

        /* Main Dashboard Grid */
        .main-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 24px; margin-bottom: 24px; }
        @media(max-width: 1024px) { .main-grid { grid-template-columns: 1fr; } }

        .panel { background: var(--panel-bg); border: 1px solid var(--border-line); border-radius: 12px; padding: 20px; margin-bottom: 24px; }
        .panel-header { font-size: 12px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; letter-spacing: 0.05em; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }

        /* Positions & Tables */
        .positions-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }
        .pos-card { background: #0b0f19; border: 1px solid #1e293b; border-radius: 8px; padding: 14px; }
        .pos-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; font-weight: 700; font-size: 13px; }
        .pos-info { display: flex; justify-content: space-between; font-size: 12px; color: var(--text-muted); margin-bottom: 6px; }
        .pos-num { color: #fff; font-weight: 600; }

        .progress-bar-bg { background: #1e293b; height: 6px; border-radius: 999px; margin-top: 10px; overflow: hidden; }
        .progress-bar-fill { background: linear-gradient(90deg, #f59e0b, #10b981); height: 100%; border-radius: 999px; }

        .radar-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 10px; background: #0b0f19; border-radius: 6px; margin-bottom: 8px; font-size: 12px; border: 1px solid #1e293b; }

        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; padding: 12px; color: var(--text-muted); border-bottom: 1px solid var(--border-line); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
        td { padding: 12px; border-bottom: 1px solid rgba(31, 41, 55, 0.5); }

        .tag-long { background: rgba(16, 185, 129, 0.15); color: var(--accent-green); padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; }
        .tag-short { background: rgba(239, 68, 68, 0.15); color: var(--accent-red); padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; }
        .pnl-pos { color: var(--accent-green); font-weight: 700; }
        .pnl-neg { color: var(--accent-red); font-weight: 700; }

        #toast { visibility: hidden; min-width: 240px; background-color: #1e293b; color: #fff; text-align: center; border-radius: 8px; padding: 12px; position: fixed; z-index: 1000; right: 30px; bottom: 30px; font-size: 13px; border: 1px solid #334155; }
        #toast.show { visibility: visible; animation: fadein 0.4s, fadeout 0.4s 2.5s; }
        @keyframes fadein { from {bottom: 0; opacity: 0;} to {bottom: 30px; opacity: 1;} }
        @keyframes fadeout { from {bottom: 30px; opacity: 1;} to {bottom: 0; opacity: 0;} }
    </style>
</head>
<body>
    <div id="toast">Command executed successfully</div>

    <!-- Top Navigation Bar -->
    <div class="top-nav">
        <div class="brand-box">
            <div class="brand-logo">AE</div>
            <div>
                <div class="brand-title">AETHEL CAPITAL MANAGEMENT</div>
                <div class="brand-sub">Global Discretionary Multi-Asset Futures Strategy</div>
            </div>
        </div>
        <div class="nav-links">
            <span class="nav-link active">Overview</span>
            <span class="nav-link">Asset Allocation</span>
            <span class="nav-link">Performance</span>
            <span class="nav-link">Risk & Factor Analytics</span>
            <span class="nav-link">Reports (FY2026)</span>
        </div>
        <div class="market-status">
            <div class="btn-group">
                <button class="btn" onclick="controlBot('pause')">Pause</button>
                <button class="btn btn-orange" onclick="controlBot('resume')">Resume</button>
                <button class="btn" style="background:#7f1d1d; border-color:#991b1b;" onclick="controlBot('closeall')">Close All</button>
            </div>
            <div class="status-pill" id="bot-status-pill">● MARKET OPEN // 10X PRO</div>
        </div>
    </div>

    <!-- Executive Header Banner -->
    <div class="exec-header">
        <div>
            <div class="exec-label">Net Asset Value (AUM)</div>
            <div class="exec-main-val" id="total-equity">$1,000.00</div>
            <div class="exec-sub">Benchmark: Binance Vision WSS (50 Assets) + Multi-Timeframe Trend</div>
        </div>
        <div class="exec-stat-box">
            <div class="exec-label">Realized Net PnL</div>
            <div class="metric-val" id="realized-pnl" style="margin-top:4px;">$0.00</div>
            <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">Live Execution Fee Included</div>
        </div>
        <div class="exec-stat-box">
            <div class="exec-label">Win Rate & Closed</div>
            <div class="metric-val" id="win-rate" style="margin-top:4px;">0.0%</div>
            <div style="font-size:11px; color:var(--text-muted); margin-top:2px;" id="total-closed-lbl">0 trades closed</div>
        </div>
        <div class="exec-stat-box">
            <div class="exec-label">Directional Exposure</div>
            <div class="metric-val" id="exposure-balance" style="margin-top:4px; color:var(--accent-orange);">0L / 0S</div>
            <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">Max Cap: 3 / Side</div>
        </div>
    </div>

    <!-- Secondary Metrics Grid -->
    <div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-title">Available Cash</div>
            <div class="metric-val" id="avail-cash">$1,000.00</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">Active Slots Occupied</div>
            <div class="metric-val" id="active-slots">0 / 5</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">Leverage Model</div>
            <div class="metric-val">10x Isolated</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">Risk Engine</div>
            <div class="metric-val" style="color:var(--accent-green);">ATR (1.5x SL / 3x TP)</div>
        </div>
    </div>

    <!-- Main Grid Layout -->
    <div class="main-grid">
        <div>
            <!-- Active Positions Panel -->
            <div class="panel">
                <div class="panel-header">
                    <span>Active Portfolio Holdings & Real-Time Performance</span>
                    <span style="font-size:10px; color:var(--accent-cyan);">WSS Feed Synchronized</span>
                </div>
                <div class="positions-grid" id="active-positions-container">
                    <div style="color: var(--text-muted); font-size: 13px; font-style: italic;">No active positions open right now...</div>
                </div>
            </div>

            <!-- Cumulative Performance Chart Panel -->
            <div class="panel">
                <div class="panel-header"><span>Cumulative Performance (FY2026 Equity Curve)</span></div>
                <canvas id="equityChart" height="75"></canvas>
            </div>
        </div>

        <div>
            <!-- Market Scanner Radar Panel -->
            <div class="panel" style="height: calc(100% - 40px);">
                <div class="panel-header"><span>Market Scanner Radar</span></div>
                <div id="radar-container">
                    <div style="color: var(--text-muted); font-size: 12px; font-style: italic;">Scanning top 50 perpetual assets...</div>
                </div>
            </div>
        </div>
    </div>

    <!-- Recent Trade Activity Table -->
    <div class="panel">
        <div class="panel-header"><span>Recent Trade Activity & Scale-Out Execution Matrix</span></div>
        <table>
            <thead>
                <tr>
                    <th>Timestamp</th>
                    <th>Asset Name</th>
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
        const equityData = { labels: [], datasets: [{ label: 'Portfolio Equity ($)', data: [], borderColor: '#f59e0b', backgroundColor: 'rgba(245, 158, 11, 0.08)', borderWidth: 2, fill: true, tension: 0.3 }] };
        const chart = new Chart(ctx, { type: 'line', data: equityData, options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#64748b', font: { size: 11 } }, grid: { color: '#1f2937' } }, y: { ticks: { color: '#64748b', font: { size: 11 } }, grid: { color: '#1f2937' } } } } });

        function showToast(msg) {
            const x = document.getElementById("toast");
            x.textContent = msg;
            x.className = "show";
            setTimeout(() => { x.className = x.className.replace("show", ""); }, 3000);
        }

        async function controlBot(action) {
            if(!confirm('Execute institutional command: ' + action.toUpperCase() + '?')) return;
            try {
                const res = await fetch('/api/control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: action })
                });
                const data = await res.json();
                showToast('Success: ' + action.toUpperCase() + ' command transmitted.');
                refreshData();
            } catch(e) { showToast('Execution Error: ' + e); }
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
                    pnlEl.className = 'metric-val ' + (m.realized_pnl >= 0 ? 'pnl-pos' : 'pnl-neg');
                    
                    document.getElementById('win-rate').textContent = m.win_rate.toFixed(1) + '%';
                    document.getElementById('total-closed-lbl').textContent = m.total_closed + ' trades closed';
                    document.getElementById('exposure-balance').textContent = m.long_count + 'L / ' + m.short_count + 'S';
                    document.getElementById('active-slots').textContent = m.active_positions_count + ' / ' + m.max_concurrent;

                    const pill = document.getElementById('bot-status-pill');
                    if (m.trading_enabled) {
                        pill.textContent = '● MARKET OPEN // 10X PRO';
                        pill.className = 'status-pill';
                    } else {
                        pill.textContent = '⏸️ TRADING PAUSED';
                        pill.className = 'status-pill paused';
                    }

                    const posContainer = document.getElementById('active-positions-container');
                    if (m.positions && m.positions.length > 0) {
                        posContainer.innerHTML = '';
                        m.positions.forEach(p => {
                            const isLong = p.side === 'LONG';
                            const pnlClass = p.unrealized_pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
                            const div = document.createElement('div');
                            div.className = 'pos-card';
                            div.innerHTML = `
                                <div class="pos-top">
                                    <span>${p.symbol} <span class="${isLong ? 'tag-long' : 'tag-short'}">${p.side} 10x</span></span>
                                    <span class="${pnlClass}">${p.unrealized_pnl >= 0 ? '+' : ''}$${p.unrealized_pnl.toFixed(2)} (${p.roe_pct >= 0 ? '+' : ''}${p.roe_pct.toFixed(1)}%)</span>
                                </div>
                                <div class="pos-info"><span>Entry Price:</span><span class="pos-num">$${p.entry_price.toFixed(5)}</span></div>
                                <div class="pos-info"><span>Live WSS Price:</span><span class="pos-num" style="color:var(--accent-cyan);">$${p.current_price.toFixed(5)}</span></div>
                                <div class="pos-info"><span>Stop-Loss / Liq:</span><span class="pos-num" style="color:var(--accent-red);">$${p.sl_price.toFixed(5)}</span></div>
                                <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: ${p.progress_pct}%;"></div></div>
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
                            item.className = 'radar-row';
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
                    const pnlCls = t.status === 'CLOSED' ? (pnlVal >= 0 ? 'pnl-pos' : 'pnl-neg') : '';
                    tr.innerHTML = `
                        <td>${t.timestamp || '-'}</td>
                        <td><b>${t.token_symbol}</b></td>
                        <td>${t.action}</td>
                        <td>$${parseFloat(t.entry_price || 0).toFixed(5)}</td>
                        <td>${t.exit_price ? '$' + parseFloat(t.exit_price).toFixed(5) : '-'}</td>
                        <td class="${pnlCls}">${pnlStr}</td>
                        <td class="${t.status === 'OPEN' ? 'tag-long' : 'status-closed'}">${t.status}</td>
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
    return VECTOR_DASHBOARD_HTML
