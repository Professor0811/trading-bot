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
    Primary: Binance Official Ticker (Rock solid, no off-market spikes).
    Fallback: DexScreener Solana Pair.
    """
    # 1. Primary: Binance API
    try:
        b_sym = cfg["binance_symbol"]
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={b_sym}", timeout=3)
        if res.status_code == 200:
            raw_price = float
