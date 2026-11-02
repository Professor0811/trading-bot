import asyncio
import random
import sqlite3
import os
from datetime import datetime
import risk_manager
import strategy_agent
from paper_engine import PaperTradingEngine
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
        # Initialize with $1000 capital if supported, otherwise engine default
        try:
            self.engine = PaperTradingEngine(initial_capital=1000.0)
        except TypeError:
            self.engine = PaperTradingEngine()
        
        # Ensure sufficient balance
        if getattr(self.engine, "cash_balance", 0) < 100:
            self.engine.cash_balance = 1000.0
            
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
                        amt = self.engine.active_position.get("amount") or self.engine.active_position.get("amount_usd", 20.0)
                        entry = self.engine.active_position.get("entry_price", current_price)
                        pnl = closed.get("pnl", 0.0)

                        record_trade_db(
                            token_symbol=symbol,
                            action="SELL",
                            amount=amt,
                            entry_price=entry,
                            exit_price=closed.get("exit_price", current_price),
                            pnl=pnl,
                            status="CLOSED"
                        )

                        alert_msg = (
                            f"🏁 *Position Closed!*\n"
                            f"• Pair: `{symbol}`\n"
                            f"• Reason: `{closed.get('reason', 'Exit Target')}`\n"
                            f"• Exit Price: `${closed.get('exit_price', current_price):.4f}`\n"
                            f"• Trade PnL: `${pnl:+.2f}`\n"
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
                        # Dynamic sizing: 2% of capital or max available safely
                        if hasattr(self.engine, "calculate_position_size"):
                            trade_amount = self.engine.calculate_position_size()
                        else:
                            trade_amount = round(self.engine.cash_balance * 0.05, 2)
                        
                        trade_amount = max(10.0, min(trade_amount, self.engine.cash_balance))

                        order_success = self.engine.execute_order(symbol, "BUY", trade_amount, current_price)
                        
                        if order_success:
                            pos = self.engine.active_position or {}
                            entry_p = pos.get("entry_price") or pos.get("exec_price") or current_price
                            tp_p = pos.get("tp_price", entry_p * 1.05)
                            sl_p = pos.get("sl_price", entry_p * 0.97)

                            record_trade_db(
                                token_symbol=symbol,
                                action="BUY",
                                amount=trade_amount,
                                entry_price=entry_p,
                                status="OPEN"
                            )

                            alert_msg = (
                                f"🔔 *Trade Executed (BUY)*\n"
                                f"• Pair: `{symbol}`\n"
                                f"• Entry Price: `${entry_p:.4f}`\n"
                                f"• Amount: `${trade_amount:.2f}`\n"
                                f"• TP Target: `${tp_p:.4f}`\n"
                                f"• SL Target: `${sl_p:.4f}`\n"
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
