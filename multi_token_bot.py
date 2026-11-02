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
        self.engine = PaperTradingEngine(initial_capital=STARTING_CAPITAL)
        self.is_running = True

    async def monitor_token(self, symbol: str):
        print(f"[{symbol}] Starting asynchronous market monitor...")

        while self.is_running:
            # Check risk daily drawdown limit
            current_drawdown = max(0.0, -self.engine.realized_pnl)
            if hasattr(risk_manager, "check_daily_loss_limit") and risk_manager.check_daily_loss_limit(self.engine.realized_pnl):
                alert_text = f"🚨 *Circuit Breaker Triggered!*\nDaily loss limit reached: `-${current_drawdown:.2f}`. Stopping bot."
                send_telegram_alert(alert_text)
                self.is_running = False
                break

            # Simulated real-time price & indicator feed
            current_price = 150.0 + random.uniform(-5.0, 5.0)
            rsi = random.randint(40, 75)
            momentum = random.uniform(0.5, 2.0)
            liquidity = random.uniform(20000.0, 100000.0)

            # Check open position exits (SL / TP)
            if self.engine.active_position and self.engine.active_position["symbol"] == symbol:
                closed = self.engine.check_exit_conditions(current_price)
                if closed:
                    record_trade_db(
                        token_symbol=symbol,
                        action="SELL",
                        amount=closed.get("amount", 50.0),
                        entry_price=self.engine.active_position["entry_price"],
                        exit_price=closed["exit_price"],
                        pnl=closed["pnl"],
                        status="CLOSED"
                    )
                    alert_msg = (
                        f"🏁 *Position Closed!*\n"
                        f"• Token: `{symbol}`\n"
                        f"• Reason: `{closed['reason']}`\n"
                        f"• Exit: `${closed['exit_price']:.4f}`\n"
                        f"• Trade PnL: `${closed['pnl']:+.2f}`\n"
                        f"• Wallet Balance: `${self.engine.cash_balance:.2f}`"
                    )
                    send_telegram_alert(alert_msg)

            # Check new entry signals if flat
            elif not self.engine.active_position:
                signal = strategy_agent.evaluate_market(
                    trend="UP",
                    rsi=rsi,
                    momentum=momentum,
                    liquidity_usd=liquidity
                )

                if signal == "BUY":
                    trade_amt = 50.0
                    if risk_manager.validate_pre_trade_safety(
                        trade_amount=trade_amt,
                        estimated_slippage=0.005,
                        liquidity_usd=liquidity,
                        is_honeypot=False
                    ):
                        order = self.engine.execute_order(symbol, "BUY", trade_amt, current_price)
                        if order:
                            record_trade_db(
                                token_symbol=symbol,
                                action="BUY",
                                amount=trade_amt,
                                entry_price=order["exec_price"],
                                status="OPEN"
                            )
                            alert_msg = (
                                f"🔔 *Order Executed (BUY)*\n"
                                f"• Token: `{symbol}`\n"
                                f"• Price: `${order['exec_price']:.4f}`\n"
                                f"• TP Target: `${order.get('tp_price', 0):.4f}`\n"
                                f"• SL Target: `${order.get('sl_price', 0):.4f}`\n"
                                f"• Available Balance: `${self.engine.cash_balance:.2f}`"
                            )
                            send_telegram_alert(alert_msg)

            await asyncio.sleep(5)

    async def run_parallel_trading(self):
        print(f"Starting parallel monitoring on {WATCH_LIST}")
        send_telegram_alert("🚀 *Autonomous Trading Bot Started Live on Render!* Monitoring pairs: `SOL`, `BONK`, `JUP`.")
        tasks = [self.monitor_token(symbol) for symbol in WATCH_LIST]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    bot = MultiTokenBot()
    try:
        asyncio.run(bot.run_parallel_trading())
    except KeyboardInterrupt:
        print("Bot stopped by user.")
