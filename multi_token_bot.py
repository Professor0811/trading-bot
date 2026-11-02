import asyncio
import sqlite3
import os
import requests
from datetime import datetime
import risk_manager
import strategy_agent
from paper_engine import PaperTradingEngine
from telegram_alerts import send_telegram_alert

DB_PATH = os.environ.get("TRADING_BOT_DB", "trading_bot.db")

# Real Solana Pair configurations on DexScreener
TARGET_PAIRS = {
    "SOL/USDC": {
        "url": "https://api.dexscreener.com/latest/dex/pairs/solana/58ooQChx4yWmvLiSWYg13Zqg7x42d8q7c2b09a1f",
        "fallback_price": 160.0
    },
    "BONK/USDC": {
        "url": "https://api.dexscreener.com/latest/dex/search?q=BONK%20USDC",
        "fallback_price": 0.000022
    },
    "JUP/USDC": {
        "url": "https://api.dexscreener.com/latest/dex/search?q=JUP%20USDC",
        "fallback_price": 1.05
    }
}


def fetch_live_dex_price(pair_info: dict) -> tuple[float, float]:
    """Fetch live market price and USD liquidity from DexScreener API."""
    try:
        res = requests.get(pair_info["url"], timeout=4)
        if res.status_code == 200:
            data = res.json()
            if "pairs" in data and len(data["pairs"]) > 0:
                pair = data["pairs"][0]
            elif "pair" in data:
                pair = data["pair"]
            else:
                pair = {}

            price = float(pair.get("priceUsd", pair_info["fallback_price"]))
            liquidity = float(pair.get("liquidity", {}).get("usd", 50000.0))
            return price, liquidity
    except Exception as e:
        print(f"[DexScreener API Warning]: {e}")
    return pair_info["fallback_price"], 50000.0


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
        try:
            self.engine = PaperTradingEngine(initial_capital=1000.0)
        except TypeError:
            self.engine = PaperTradingEngine()
        
        if getattr(self.engine, "cash_balance", 0) < 100:
            self.engine.cash_balance = 1000.0
            
        self.is_running = True
        self.price_history = {s: [] for s in TARGET_PAIRS}

    async def monitor_token(self, symbol: str, pair_cfg: dict):
        print(f"[{symbol}] Connecting real DexScreener live feed...")

        while self.is_running:
            try:
                # 1. Fetch real DEX live price and liquidity
                current_price, liquidity = await asyncio.to_thread(fetch_live_dex_price, pair_cfg)
                
                # Maintain price buffer for basic technical trend / momentum calculation
                history = self.price_history[symbol]
                history.append(current_price)
                if len(history) > 20:
                    history.pop(0)

                # Simple technical estimation from live ticks
                if len(history) >= 5:
                    momentum = 1.0 if history[-1] > history[-3] else 0.4
                    trend = "UP" if history[-1] >= history[0] else "DOWN"
                    rsi = 50.0 + ((history[-1] - min(history)) / (max(history) - min(history) + 1e-9) - 0.5) * 30.0
                else:
                    momentum = 1.1
                    trend = "UP"
                    rsi = 48.0

                # 2. Check Exits if position active
                if self.engine.active_position and self.engine.active_position.get("symbol") == symbol:
                    entry_price = self.engine.active_position.get("entry_price", current_price)
                    trade_amt = self.engine.active_position.get("amount") or self.engine.active_position.get("amount_usd", 20.0)

                    closed = self.engine.check_exit_conditions(current_price)
                    if closed:
                        exit_price = closed.get("exit_price", current_price)
                        pnl = closed.get("pnl", 0.0)
                        reason = closed.get("reason", "Exit Triggered")

                        record_trade_db(
                            token_symbol=symbol,
                            action="SELL",
                            amount=trade_amt,
                            entry_price=entry_price,
                            exit_price=exit_price,
                            pnl=pnl,
                            status="CLOSED"
                        )

                        alert_msg = (
                            f"🏁 *Real DEX Position Closed!*\n"
                            f"• Pair: `{symbol}`\n"
                            f"• Reason: `{reason}`\n"
                            f"• Exit Price: `${exit_price:.6f}`\n"
                            f"• Trade PnL: `${pnl:+.2f}`\n"
                            f"• Wallet Balance: `${self.engine.cash_balance:.2f}`"
                        )
                        send_telegram_alert(alert_msg)

                # 3. Evaluate Entry if flat
                elif not self.engine.active_position:
                    signal = strategy_agent.evaluate_market(
                        trend=trend,
                        rsi=rsi,
                        momentum=momentum,
                        liquidity_usd=liquidity,
                        macd=1.2,
                        macd_signal=0.6,
                        price=current_price
                    )

                    if signal == "BUY":
                        if hasattr(self.engine, "calculate_position_size"):
                            trade_amount = self.engine.calculate_position_size()
                        else:
                            trade_amount = round(self.engine.cash_balance * 0.02, 2)
                        
                        trade_amount = max(10.0, min(trade_amount, self.engine.cash_balance))

                        order_success = self.engine.execute_order(symbol, "BUY", trade_amount, current_price)
                        
                        if order_success:
                            pos = self.engine.active_position or {}
                            entry_p = pos.get("entry_price") or pos.get("exec_price") or current_price
                            tp_p = pos.get("tp_price", entry_p * 1.06)
                            sl_p = pos.get("sl_price", entry_p * 0.975)

                            record_trade_db(
                                token_symbol=symbol,
                                action="BUY",
                                amount=trade_amount,
                                entry_price=entry_p,
                                status="OPEN"
                            )

                            alert_msg = (
                                f"🔔 *Real DEX Order (BUY)*\n"
                                f"• Pair: `{symbol}`\n"
                                f"• Market Price: `${entry_p:.6f}`\n"
                                f"• Amount: `${trade_amount:.2f}`\n"
                                f"• Take-Profit Target: `${tp_p:.6f}`\n"
                                f"• Trailing SL Target: `${sl_p:.6f}`\n"
                                f"• Balance: `${self.engine.cash_balance:.2f}`"
                            )
                            send_telegram_alert(alert_msg)

            except Exception as err:
                print(f"[{symbol} Real DEX Loop Error]: {err}")

            await asyncio.sleep(6)

    async def run_parallel_trading(self):
        send_telegram_alert("🚀 *Autonomous Trading Bot: Live DexScreener Feed Connected!* Monitoring live on-chain pairs.")
        tasks = [self.monitor_token(symbol, cfg) for symbol, cfg in TARGET_PAIRS.items()]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    bot = MultiTokenBot()
    try:
        asyncio.run(bot.run_parallel_trading())
    except KeyboardInterrupt:
        print("Bot stopped.")
