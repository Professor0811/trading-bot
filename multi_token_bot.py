import asyncio
import random
import sqlite3
import os
from datetime import datetime
import risk_manager
import strategy_agent
from paper_engine import PaperTradingEngine
from config import STARTING_CAPITAL
from telegram_alerts import send_telegram_alert

DB_PATH = os.environ.get("TRADING_BOT_DB", "trading_bot.db")
WATCH_LIST = ["SOL/USDC", "BONK/USDC", "JUP/USDC"]


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
        # Uses starting capital from config
        self.engine = PaperTradingEngine()
        self.is_running = True

    async def monitor_token(self, symbol: str):
        print(f"[{symbol}] Starting asynchronous market monitor...")

        while self.is_running:
            try:
                # 1. Market Simulation Price Tick
                current_price = round(150.0 + random.uniform(-6.0, 6.0), 4)
                rsi = random.randint(35, 75)
                momentum = random.uniform(0.5, 2.0)
                liquidity = 55000.0

                # 2. Check Exits if position is active for this symbol
                if self.engine.active_position and self.engine.active_position.get("symbol") == symbol:
                    closed = self.engine.check_exit_conditions(current_price)
                    if closed:
                        # Record closed trade into DB
                        record_trade_db(
                            token_symbol=symbol,
                            action="SELL",
                            amount=50.0,
                            entry_price=closed.get("entry_price", current_price),
                            exit_price=closed.get("exit_price", current_price),
                            pnl=closed.get("pnl", 0.0),
                            status="CLOSED"
                        )
                        # Send Instant Close Alert to Telegram
                        alert_msg = (
                            f"🏁 *Position Closed!*\n"
                            f"• Pair: `{symbol}`\n"
                            f"• Reason: `{closed.get('reason', 'Exit Target')}`\n"
                            f"• Exit Price: `${closed.get('exit_price', current_price):.4f}`\n"
                            f"• Trade PnL: `${closed.get('pnl', 0.0):+.2f}`\n"
                            f"• Wallet Balance: `${self.engine.cash_balance:.2f}`"
                        )
                        send_telegram_alert(alert_msg)

                # 3. If flat, check entry criteria
                elif not self.engine.active_position:
                    try:
                        signal = strategy_agent.evaluate_market(
                            trend="UP", rsi=rsi, momentum=momentum, liquidity_usd=liquidity
                        )
                    except TypeError:
                        signal = strategy_agent.evaluate_market(
                            trend="UP", rsi=rsi, momentum=momentum,
                            liquidity_usd=liquidity, macd=1.0, macd_signal=0.5,
                            price=current_price, bb_lower=current_price * 0.98,
                            news_feed="Bullish"
                        )

                    if signal == "BUY":
                        trade_amount = 50.0
                        # Execute paper order (compatible with boolean or dict return)
                        order_success = self.engine.execute_order(symbol, "BUY", trade_amount, current_price)
                        
                        if order_success:
                            pos = self.engine.active_position or {}
                            entry_p = pos.get("entry_price") or pos.get("exec_price") or current_price
                            tp_p = pos.get("tp_price", entry_p * 1.05)
                            sl_p = pos.get("sl_price", entry_p * 0.97)

                            # Record open BUY trade into SQLite DB
                            record_trade_db(
                                token_symbol=symbol,
                                action="BUY",
                                amount=trade_amount,
                                entry_price=entry_p,
                                status="OPEN"
                            )

                            # Send Instant BUY Alert to Telegram
                            alert_msg = (
                                f"🔔 *Trade Executed (BUY)*\n"
                                f"• Pair: `{symbol}`\n"
                                f"• Entry Price: `${entry_p:.4f}`\n"
                                f"• Take-Profit (TP): `${tp_p:.4f}`\n"
                                f"• Stop-Loss (SL): `${sl_p:.4f}`\n"
                                f"• Wallet Balance: `${self.engine.cash_balance:.2f}`"
                            )
                            send_telegram_alert(alert_msg)

            except Exception as err:
                print(f"[{symbol} Loop Error]: {err}")

            await asyncio.sleep(4)

    async def run_parallel_trading(self):
        send_telegram_alert("🚀 *Autonomous Trading Bot Started Live on Render!* Monitoring pairs: `SOL`, `BONK`, `JUP`.")
        tasks = [self.monitor_token(symbol) for symbol in WATCH_LIST]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    bot = MultiTokenBot()
    try:
        asyncio.run(bot.run_parallel_trading())
    except KeyboardInterrupt:
        print("Bot stopped.")
