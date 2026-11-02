import sqlite3
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
from trade_logger import init_db

app = FastAPI(title="Interactive Real-Time Charting Dashboard")
DB_NAME = "trades.db"

def get_dashboard_data():
    init_db()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, timestamp, symbol, side, exec_price, amount_usd, pnl, reason, wallet_cash 
        FROM trade_history 
        ORDER BY id ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    # Calculate live metrics
    wallet_cash = rows[-1][8] if rows else 1000.00
    sell_trades = [r for r in rows if r[3] == "SELL"]
    total_closed = len(sell_trades)
    wins = sum(1 for r in sell_trades if r[6] > 0)
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0
    total_pnl = sum(r[6] for r in sell_trades)

    # Prepare chart labels (timestamps) and data points (wallet cash balance progression)
    chart_labels = [r[1] for r in rows]
    chart_data = [r[8] for r in rows]

    return {
        "wallet_cash": wallet_cash,
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "total_closed": total_closed,
        "wins": wins,
        "losses": total_closed - wins,
        "trades": list(reversed(rows)), # Latest first for table
        "chart_labels": chart_labels,
        "chart_data": chart_data
    }

@app.get("/", response_class=HTMLResponse)
def render_dashboard():
    data = get_dashboard_data()
    pnl_color = "#10b981" if data["total_pnl"] >= 0 else "#ef4444"

    rows_html = ""
    for r in data["trades"]:
        side_badge = (
            '<span style="background:#1e3a8a;color:#93c5fd;padding:4px 8px;border-radius:4px;font-weight:bold;">BUY</span>'
            if r[3] == "BUY" else
            '<span style="background:#064e3b;color:#6ee7b7;padding:4px 8px;border-radius:4px;font-weight:bold;">SELL</span>'
        )
        row_pnl_color = "#10b981" if r[6] > 0 else ("#ef4444" if r[6] < 0 else "#9ca3af")
        rows_html += f"""
        <tr>
            <td>#{r[0]}</td>
            <td>{r[1]}</td>
            <td><strong>{r[2]}</strong></td>
            <td>{side_badge}</td>
            <td>${r[4]:.4f}</td>
            <td style="color:{row_pnl_color};font-weight:bold;">${r[6]:+.2f}</td>
            <td>{r[7]}</td>
            <td>${r[8]:.2f}</td>
        </tr>
        """

    if not rows_html:
        rows_html = '<tr><td colspan="8" style="text-align:center;padding:20px;">No trades logged yet!</td></tr>'

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Interactive Trading Bot Dashboard</title>
        <meta http-equiv="refresh" content="5">
        <!-- Include Chart.js from CDN -->
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 25px; }}
            .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 15px; margin-bottom: 25px; }}
            .status-badge {{ background: #065f46; color: #34d399; padding: 6px 14px; border-radius: 20px; font-size: 14px; font-weight: bold; }}
            .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 30px; }}
            .card {{ background: #1e293b; padding: 20px; border-radius: 10px; border: 1px solid #334155; }}
            .card-title {{ color: #94a3b8; font-size: 13px; text-transform: uppercase; margin-bottom: 8px; }}
            .card-value {{ font-size: 26px; font-weight: bold; }}
            .chart-container {{ background: #1e293b; padding: 20px; border-radius: 10px; border: 1px solid #334155; margin-bottom: 30px; }}
            table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 10px; overflow: hidden; border: 1px solid #334155; }}
            th {{ background: #334155; color: #cbd5e1; text-align: left; padding: 14px; font-size: 14px; }}
            td {{ padding: 12px 14px; border-bottom: 1px solid #334155; font-size: 14px; }}
            tr:hover {{ background-color: #263349; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div>
                <h1 style="margin:0;font-size:24px;">⚡ Autonomous Crypto Trading Bot & AI Analytics</h1>
                <p style="margin:5px 0 0 0;color:#94a3b8;font-size:14px;">Connected to SQLite DB • Live Charting & Multi-Agent AI Active • Auto-refreshes every 5s</p>
            </div>
            <div class="status-badge">● SYSTEM ACTIVE (DEX & AI ON)</div>
        </div>

        <div class="cards">
            <div class="card">
                <div class="card-title">Wallet Cash Balance</div>
                <div class="card-value">${data['wallet_cash']:.2f}</div>
            </div>
            <div class="card">
                <div class="card-title">Total Realized PnL</div>
                <div class="card-value" style="color:{pnl_color};">${data['total_pnl']:+.2f}</div>
            </div>
            <div class="card">
                <div class="card-title">Strategy Win Rate</div>
                <div class="card-value">{data['win_rate']:.1f}%</div>
            </div>
            <div class="card">
                <div class="card-title">Closed Trades (W / L)</div>
                <div class="card-value">{data['total_closed']} <span style="font-size:16px;color:#94a3b8;">({data['wins']}W / {data['losses']}L)</span></div>
            </div>
        </div>

        <div class="chart-container">
            <h2 style="font-size:18px;margin-top:0;margin-bottom:15px;color:#cbd5e1;">📈 Real-Time Wallet Balance Progression</h2>
            <canvas id="walletChart" height="80"></canvas>
        </div>

        <h2 style="font-size:18px;margin-bottom:12px;">📒 Live SQLite Trade History</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Timestamp</th>
                    <th>Pair</th>
                    <th>Side</th>
                    <th>Exec Price</th>
                    <th>Realized PnL</th>
                    <th>Trigger / Reason</th>
                    <th>Wallet Cash</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <script>
            const ctx = document.getElementById('walletChart').getContext('2d');
            const walletChart = new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: {data['chart_labels']},
                    datasets: [{{
                        label: 'Wallet Balance ($ USD)',
                        data: {data['chart_data']},
                        borderColor: '#38bdf8',
                        backgroundColor: 'rgba(56, 189, 248, 0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.3
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{
                        legend: {{ labels: {{ color: '#f8fafc' }} }}
                    }},
                    scales: {{
                        x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }},
                        y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }}
                    }}
                }}
            }});
        </script>
    </body>
    </html>
    """
    return html_content

if __name__ == "__main__":
    print("Starting Interactive Charting Dashboard on http://127.0.0.1:8000 ...")
    uvicorn.run(app, host="127.0.0.1", port=8000)