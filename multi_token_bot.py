import asyncio
import sqlite3
import os
import requests
from datetime import datetime
import config
import risk_manager
import strategy_agent
from paper_engine import PaperTradingEngine
from telegram_alerts import send_telegram_alert

DB_PATH = os.environ.get("TRADING_BOT_DB", "trading_bot.db")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TOKENS = {
    "SOL/USDC": {
        "binance_symbol": "SOLUSDT",
        "dex_url": "https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112",
        "fallback": 93.50
    },
    "JUP/USDC": {
        "binance_symbol": "JUPUSDT",
        "dex_url": "https://api.dexscreener.com/latest/dex/tokens/JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
        "fallback": 1.05
    },
    "BONK/USDC": {
        "binance_symbol": "1000BONKUSDT",
        "dex_url": "https://api.dexscreener.com/latest/dex/pairs/solana/DBrEeaP4o45m83q63rS5yHqU2X3uU1b47r1Z9xK6j6z",
        "fallback": 0.000022
    }
}


def fmt_p(val: float) -> str:
    """Safely format prices across macro and micro token scales."""
    if val is None:
        return "0.00"
    val = float(val)
    if val < 0.0001:
        return f"{val:.8f}".rstrip("0").rstrip(".")
    elif val < 1.0:
        return f"{val:.6f}"
    return f"{val:.4f}"


def fetch_live_price(symbol: str, cfg: dict) -> tuple:
    """
    Primary: Binance Official Ticker.
    Fallback: DexScreener Solana Pair.
    """
    # 1. Primary: Binance API
    try:
        b_sym = cfg["binance_symbol"]
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={b_sym}", timeout=3)
        if res.status_code == 200:
            raw_price = float(res.json()["price"])
            if b_sym == "1000BONKUSDT":
                raw_price = raw_price / 1000.0
            if raw_price > 0:
                return raw_price, 500000.0
    except Exception:
        pass

    # 2. Fallback: DexScreener
    try:
        res = requests.get(cfg["dex_url"], timeout=3)
        if res.status_code == 200:
            data = res.json()
            pairs = data.get("pairs") or ([data.get("pair")] if data.get("pair") else [])
            valid_pairs = [p for p in pairs if p and float(p.get("priceUsd", 0.0) or 0.0) > 0]
            if valid_pairs:
                top_pair = max(valid_pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0.0) or 0.0))
                price = float(top_pair["priceUsd"])
                liquidity = float(top_pair.get("liquidity", {}).get("usd", 50000.0) or 50000.0)
                if symbol == "SOL/USDC" and (price > 150.0 or price < 50.0):
                    return cfg["fallback"], 50000.0
                return price, liquidity
    except Exception as e:
        print(f"[{symbol} DEX Fallback Error]: {e}")

    return cfg["fallback"], 50000.0


def record_trade_db(token_symbol, action, amount, entry_price, exit_price=None, pnl=0.0, status="OPEN"):
    """Persist trade execution and exit records to SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO trades (token_symbol, action, amount, entry_price, exit_price, pnl, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (token_symbol, action, amount, entry_price, exit_price, pnl, status))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB Error]: {e}")


class MultiTokenBot:
    def __init__(self):
        self.engine = PaperTradingEngine(
            initial_capital=config.STARTING_CAPITAL,
            max_concurrent=config.MAX_CONCURRENT_TRADES
        )
        self.is_running = True
        self.trading_enabled = True
        self.circuit_breaker_alerted = False
        self.latest_prices = {}
        self.price_history = {s: [] for s in TOKENS}

    async def telegram_command_listener(self):
        """Poll Telegram for interactive commands."""
        if not BOT_TOKEN:
            return

        last_update_id = 0
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

        while self.is_running:
            try:
                params = {"timeout": 10, "offset": last_update_id + 1}
                res = await asyncio.to_thread(requests.get, url, params=params, timeout=12)
                if res.status_code == 200:
                    data = res.json()
                    for item in data.get("result", []):
                        last_update_id = item["update_id"]
                        msg = item.get("message", {})
                        text = msg.get("text", "").strip()
                        sender_id = str(msg.get("chat", {}).get("id", ""))

                        if CHAT_ID and sender_id != str(CHAT_ID):
                            continue

                        if text == "/status":
                            active_desc = []
                            for sym, p in self.engine.positions.items():
                                active_desc.append(
                                    f"• `{sym}` ({p['side']} {self.engine.leverage}x): Margin ${p['margin']:.2f} | "
                                    f"Entry ${fmt_p(p['entry_price'])} | TP ${fmt_p(p['tp_price'])}"
                                )
                            pos_text = "\n".join(active_desc) if active_desc else "None (0/3 Active Slots)"

                            status_reply = (
                                f"📊 *{self.engine.leverage}x Futures Bot Status:*\n"
                                f"• Engine State: `{'ACTIVE' if self.trading_enabled else 'PAUSED'}`\n"
                                f"• Available Cash: `${self.engine.cash_balance:.2f}
