import os
import sqlite3
import asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from multi_token_bot import MultiTokenBot

app = FastAPI(title="Autonomous 5x Futures Bot Monitor")

DB_PATH = os.environ.get("TRADING_BOT_DB", "trading_bot.db")


def init_db():
    """Ensure trades table exists immediately upon app startup."""
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
                pnl REAL DEFAULT 0.0,
                status TEXT DEFAULT 'OPEN'
            )
        """)
        conn.commit()
        conn.close()
        print("[DB Init]: trades table verified successfully.")
    except Exception as e:
        print(f"[DB Init Error]: {e}")


# Initialize table right away
init_db()

bot_instance = MultiTokenBot()


@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(bot_instance.run_parallel_trading())


@app.get("/healthz")
async def health_check():
    return {"status": "ok", "engine": "running"}


@app.get("/api/metrics")
async def get_metrics():
    engine = bot_instance.engine

    locked_margin = sum(p.get("margin", 0.0) for p in engine.positions.values())
    total_equity = engine.cash_balance + locked_margin

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
    except Exception:
        return []


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Autonomous 5x Futures Bot Monitor</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-base: #0b0f19;
            --card-bg: #111827;
            --border-color: #1f2937;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg-base);
            color: var(--text-main);
            margin: 0;
            padding: 24px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
        }
        .header h1 {
            margin: 0;
            font-size: 1.5rem;
        }
        .status-badge {
            background-color: rgba(34, 197, 94, 0.15);
            color: #22c55e;
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 0.85rem;
            font-weight: bold;
            border: 1px solid rgba(34, 197, 94, 0.3);
        }
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .metric-card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
        }
        .metric-title {
            font-size: 0.8rem;
            color: var(--text-muted);
            text-transform: uppercase;
            margin-bottom: 8px;
        }
        .metric-value {
            font-size: 1.6rem;
            font-weight: 700;
        }
        .metric-sub {
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-top: 4px;
        }
        .chart-card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }
        th, td {
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
        }
        th {
            color: var(--text-muted);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.75rem;
        }
        .badge-open { color: #38bdf8; font-weight: bold; }
        .badge-closed { color: var(--text-muted); }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>⚡ 5x Futures Trading Bot Monitor</h1>
            <div style="color: var(--text-muted); font-size: 0.85rem; margin-top: 4px;">
                SOL, BONK, JUP • Bi-Directional (Long & Short) • 3 Concurrent Slots
            </div>
        </div>
        <div class="status-badge">ONLINE • 5X ACTIVE</div>
    </div>

    <div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-title">Total Portfolio Equity</div>
            <div class="metric-value" style="color: #60a5fa;" id="totalEquity">$1,000.00</div>
            <div class="metric-sub" id="lockedMargin">Locked Margin: $0.00</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">Available Cash</div>
            <div class="metric-value" id="availableCash">$1,000.00</div>
            <div class="metric-sub">Unallocated Capital</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">Total Realized PnL</div>
            <div class="metric-value" id="totalPnl">+$0.00</div>
            <div class="metric-sub" id="pnlSub">Closed trades net</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">Win Rate / Trades</div>
            <div class="metric-value" id="winRate">0.0%</div>
            <div class="metric-sub" id="closedCount">0 closed trades</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">Active Slots</div>
            <div class="metric-value" style="color: #f59e0b;" id="activeSlots">0/3</div>
            <div class="metric-sub">Parallel trade cap</div>
        </div>
    </div>

    <div class="chart-card">
        <div class="metric-title" style="margin-bottom: 16px;">Portfolio Equity Trajectory</div>
        <div style="height: 260px;">
            <canvas id="equityChart"></canvas>
        </div>
    </div>

    <div class="chart-card">
        <div class="metric-title" style="margin-bottom: 16px;">Recent Trade Activity</div>
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
            <tbody id="tradeRows">
                <tr><td colspan="7" style="text-align: center; color: var(--text-muted);">Awaiting trade stream...</td></tr>
            </tbody>
        </table>
    </div>

    <script>
        const ctx = document.getElementById('equityChart').getContext('2d');
        const equityChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: ['Start'],
                datasets: [{
                    label: 'Portfolio Equity ($)',
                    data: [1000.00],
                    borderColor: '#38bdf8',
                    backgroundColor: 'rgba(56, 189, 248, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { grid: { color: '#1f2937' }, ticks: { color: '#9ca3af' } },
                    y: { grid: { color: '#1f2937' }, ticks: { color: '#9ca3af' } }
                },
                plugins: { legend: { display: false } }
            }
        });

        function fmtPrice(val) {
            if (val === null || val === undefined) return '-';
            const num = parseFloat(val);
            if (num < 0.0001) return '$' + num.toFixed(8);
            if (num < 1.0) return '$' + num.toFixed(6);
            return '$' + num.toFixed(4);
        }

        async function refreshMetrics() {
            try {
                const res = await fetch('/api/metrics');
                if (res.ok) {
                    const data = await res.json();
                    document.getElementById('totalEquity').innerText = '$' + data.total_equity.toFixed(2);
                    document.getElementById('lockedMargin').innerText = 'Locked Margin: $' + data.locked_margin.toFixed(2);
                    document.getElementById('availableCash').innerText = '$' + data.available_cash.toFixed(2);
                    
                    const pnlEl = document.getElementById('totalPnl');
                    pnlEl.innerText = (data.realized_pnl >= 0 ? '+' : '') + '$' + data.realized_pnl.toFixed(2);
                    pnlEl.style.color = data.realized_pnl >= 0 ? '#22c55e' : '#ef4444';

                    document.getElementById('winRate').innerText = data.win_rate + '%';
                    document.getElementById('closedCount').innerText = data.closed_trades + ' closed trades';
                    document.getElementById('activeSlots').innerText = data.active_slots;

                    if (equityChart.data.datasets[0].data.length < 25) {
                        equityChart.data.labels.push(new Date().toLocaleTimeString());
                        equityChart.data.datasets[0].data.push(data.total_equity);
                        equityChart.update();
                    }
                }
            } catch (err) {}
        }

        async function refreshTrades() {
            try {
                const res = await fetch('/api/trades');
                if (res.ok) {
                    const trades = await res.json();
                    if (trades.length === 0) return;

                    const tbody = document.getElementById('tradeRows');
                    tbody.innerHTML = trades.map(t => {
                        const pnlColor = t.pnl > 0 ? '#22c55e' : (t.pnl < 0 ? '#ef4444' : 'inherit');
                        const pnlText = t.status === 'CLOSED' ? (t.pnl >= 0 ? '+' : '') + '$' + parseFloat(t.pnl).toFixed(2) : '-';
                        return `
                            <tr>
                                <td>${t.time}</td>
                                <td><strong>${t.token}</strong></td>
                                <td>${t.action}</td>
                                <td>${fmtPrice(t.entry_price)}</td>
                                <td>${fmtPrice(t.exit_price)}</td>
                                <td style="color: ${pnlColor}; font-weight: bold;">${pnlText}</td>
                                <td class="${t.status === 'OPEN' ? 'badge-open' : 'badge-closed'}">${t.status}</td>
                            </tr>
                        `;
                    }).join('');
                }
            } catch (err) {}
        }

        setInterval(refreshMetrics, 4000);
        setInterval(refreshTrades, 5000);
        refreshMetrics();
        refreshTrades();
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    return HTMLResponse(content=HTML_TEMPLATE)
