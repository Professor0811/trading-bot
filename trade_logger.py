import sqlite3
from datetime import datetime

DB_NAME = "trades.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            side TEXT,
            exec_price REAL,
            amount_usd REAL,
            pnl REAL,
            reason TEXT,
            wallet_cash REAL
        )
    """)
    conn.commit()
    conn.close()

def log_trade(timestamp, symbol, side, exec_price, amount_usd, pnl, reason, wallet_cash):
    init_db()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO trade_history (timestamp, symbol, side, exec_price, amount_usd, pnl, reason, wallet_cash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (timestamp, symbol, side, exec_price, amount_usd, pnl, reason, wallet_cash))
    conn.commit()
    conn.close()

def view_logs():
    init_db()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trade_history")
    rows = cursor.fetchall()
    conn.close()

    print("==================================================================================")
    print(" 📋 PERMANENT SQLITE TRADE JOURNAL (trades.db) ")
    print("==================================================================================")
    print(f"{'ID':<3} | {'Timestamp':<19} | {'Pair':<8} | {'Side':<4} | {'Price':<9} | {'PnL':<9} | {'Reason':<22} | {'Cash':<9}")
    print("-" * 90)
    for r in rows:
        print(f"#{r[0]:<2} | {r[1]} | {r[2]:<8} | {r[3]:<4} | ${r[4]:<8.4f} | ${r[6]:<+8.2f} | {r[7]:<22} | ${r[8]:<8.2f}")
    print("==================================================================================")

if __name__ == "__main__":
    view_logs()