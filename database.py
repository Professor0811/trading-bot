import os
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL")
SQLITE_PATH = os.environ.get("TRADING_BOT_DB", "trading_bot.db")

is_postgres = False
if DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")):
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        is_postgres = True
    except ImportError:
        is_postgres = False


def get_connection():
    if is_postgres:
        # Handle postgres:// vs postgresql:// compatibility
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url)
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def init_db():
    try:
        conn = get_connection()
        cur = conn.cursor()
        if is_postgres:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    token_symbol VARCHAR(30),
                    action VARCHAR(30),
                    amount DOUBLE PRECISION,
                    entry_price DOUBLE PRECISION,
                    exit_price DOUBLE PRECISION,
                    pnl DOUBLE PRECISION,
                    status VARCHAR(20)
                );
            """)
        else:
            cur.execute("""
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
                );
            """)
        conn.commit()
        cur.close()
        conn.close()
        print(f"[Database] Initialized successfully. Engine: {'PostgreSQL (Cloud Supabase)' if is_postgres else 'SQLite (Local)'}")
    except Exception as e:
        print("[Database Init Error]:", e)


def record_trade(token_symbol, action, amount, entry_price, exit_price=None, pnl=0.0, status="OPEN"):
    try:
        conn = get_connection()
        cur = conn.cursor()
        param_placeholder = "%s" if is_postgres else "?"
        query = f"""
            INSERT INTO trades (token_symbol, action, amount, entry_price, exit_price, pnl, status)
            VALUES ({param_placeholder}, {param_placeholder}, {param_placeholder}, {param_placeholder}, {param_placeholder}, {param_placeholder}, {param_placeholder})
        """
        cur.execute(query, (token_symbol, action, amount, entry_price, exit_price, pnl, status))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("[Database Insert Error]:", e)


def fetch_recent_trades(limit=50):
    trades = []
    try:
        conn = get_connection()
        if is_postgres:
            cur = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cur = conn.cursor()

        cur.execute(f"SELECT id, timestamp, token_symbol, action, amount, entry_price, exit_price, pnl, status FROM trades ORDER BY id DESC LIMIT {limit}")
        rows = cur.fetchall()
        for r in rows:
            trades.append(dict(r))
        cur.close()
        conn.close()
    except Exception as e:
        print("[Database Fetch Error]:", e)
    return trades


def fetch_closed_stats():
    total_closed = 0
    winning_trades = 0
    closed_pnls = []
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) FROM trades WHERE status = 'CLOSED'")
        row = cur.fetchone()
        if row and row[0]:
            total_closed = row[0]
            winning_trades = row[1] if row[1] else 0

        cur.execute("SELECT pnl FROM trades WHERE status = 'CLOSED' ORDER BY id ASC")
        rows = cur.fetchall()
        closed_pnls = [float(r[0]) for r in rows if r[0] is not None]
        cur.close()
        conn.close()
    except Exception as e:
        print("[Database Stats Error]:", e)
    return total_closed, winning_trades, closed_pnls
