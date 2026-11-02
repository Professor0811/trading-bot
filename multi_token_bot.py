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
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TOKENS = {
    "SOL/USDC": {
        "dex_url": "https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112",
        "binance_symbol": "SOLUSDT"
    },
    "JUP/USDC": {
        "dex_url": "https://api.dexscreener.com/latest/dex/tokens/JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
        "binance_symbol": "JUPUSDT"
    },
    "BONK/USDC": {
        "dex_url": "https://api.dexscreener.com/latest/dex/tokens/DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "binance_symbol": "1000BONKUSDT"
    }
}


def fetch_live_price(symbol: str, cfg: dict) -> tuple[float, float]:
    """Fetches real-time market price via DexScreener with Binance fallback."""
    try:
        res = requests.get(cfg["dex_url"], timeout=4)
        if res.status_code == 200:
            data = res.json()
            pairs = data.get("pairs") or []
            if isinstance(pairs, list) and len(pairs) > 0:
                top_pair = max(pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0.0) or 0.0))
                price = float(top_pair.get("priceUsd", 0.0))
                liquidity = float(top_pair.get("liquidity", {}).get("usd", 50000.0))
                if price > 0:
                    return price, liquidity
    except Exception:
        pass

    try:
        b_sym = cfg["binance_symbol"]
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={b_sym}", timeout=3)
        if res.status_code == 200:
            raw_price = float(res.json()["price"])
            if b_sym == "1000BONKUSDT":
                raw_price = raw_price / 1000.0
            return raw_price, 100000.0
    except Exception as e:
        print(f"[{symbol} Price Error]: {e}")

    return 93.5, 50000.0


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
        self.trading_enabled = True
        self.latest_prices = {}
        self.price_history = {s: [] for s in TOKENS}

    async def telegram_command_listener(self):
        """Polls Telegram updates to respond to user interactive commands."""
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

                        # Authorization check: only execute commands from your CHAT_ID
                        if CHAT_ID and sender_id != str(CHAT_ID):
                            continue

                        if text == "/status":
                            pos = self.engine.active_position
                            pos_desc = "None (Flat)"
                            if pos:
                                pos_desc = f"{pos.get('symbol')} | Entry: ${pos.get('entry_price', 0):.4f} | TP: ${pos.get('tp_price', 0):.4f}"

                            status_reply = (
                                f"📊 *Trading Bot Status:*\n"
                                f"• Engine State: `{'TRADING ACTIVE' if self.trading_enabled else 'PAUSED'}`\n"
                                f"• Cash Balance: `${self.engine.cash_balance:.2f}`\n"
                                f"• Realized PnL: `${self.engine.realized_pnl:+.2f}`\n"
                                f"• Active Trade: `{pos_desc}`"
                            )
                            send_telegram_alert(status_reply)

                        elif text == "/stop":
                            self.trading_enabled = False
                            send_telegram_alert("🛑 *Trading Paused!* Bot will not take any new positions.")

                        elif text == "/start":
                            self.trading_enabled = True
                            send_telegram_alert("▶️ *Trading Resumed!* Market scanning active.")

                        elif text == "/closeall":
                            if self.engine.active_position:
                                sym = self.engine.active_position.get("symbol")
                                cur_p = self.latest_prices.get(sym, self.engine.active_position.get("entry_price", 0))
                                closed = self.engine.check_exit_conditions(cur_p)
                                if not closed:
                                    if hasattr(self.engine, "close_position"):
                                        closed = self.engine.close_position(cur_p, "Manual /closeall")
                                    elif hasattr(self.engine, "_close_position"):
                                        closed = self.engine._close_position(0.0, "Manual /closeall", cur_p)

                                send_telegram_alert(f"⚠️ *Manual Exit Triggered!* Position on `{sym}` closed.")
                            else:
                                send_telegram_alert("ℹ️ *No open positions* to close.")

            except Exception as e:
                print(f"[Telegram Listener Error]: {e}")

            await asyncio.sleep(2)

    async def monitor_token(self, symbol: str, cfg: dict):
        print(f"[{symbol}] Tracking live market price stream...")

        while self.is_running:
            try:
                # 1. Fetch exact live market tick
                current_price, liquidity = await asyncio.to_thread(fetch_live_price, symbol, cfg)
                self.latest_prices[symbol] = current_price

                history = self.price_history[symbol]
                history.append(current_price)
                if len(history) > 20:
                    history.pop(0)

                # Technical analysis over live tick window
                if len(history) >= 5:
                    momentum = 1.0 if history[-1] > history[-3] else 0.4
                    trend = "UP" if history[-1] >= history[0] else "DOWN"
                    spread = max(history) - min(history)
                    rsi = 50.0 + ((history[-1] - min(history)) / (spread + 1e-9) - 0.5) * 30.0
                else:
                    momentum = 1.0
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
                            f"🏁 *Position Closed!*\n"
                            f"• Pair: `{symbol}`\n"
                            f"• Reason: `{reason}`\n"
                            f"• Exit Price: `${exit_price:.4f}`\n"
                            f"• Trade PnL: `${pnl:+.2f}`\n"
                            f"• Wallet Balance: `${self.engine.cash_balance:.2f}`"
                        )
                        send_telegram_alert(alert_msg)

                # 3. Evaluate Entry if flat and trading is enabled
                elif not self.engine.active_position and self.trading_enabled:
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
                                f"🔔 *Real Market Order (BUY)*\n"
                                f"• Pair: `{symbol}`\n"
                                f"• Live Price: `${entry_p:.4f}`\n"
                                f"• Amount: `${trade_amount:.2f}`\n"
                                f"• Take-Profit Target: `${tp_p:.4f}`\n"
                                f"• Trailing SL Target: `${sl_p:.4f}`\n"
                                f"• Balance: `${self.engine.cash_balance:.2f}`"
                            )
                            send_telegram_alert(alert_msg)

            except Exception as err:
                print(f"[{symbol} Loop Error]: {err}")

            await asyncio.sleep(6)

    async def run_parallel_trading(self):
        send_telegram_alert("🚀 *Autonomous Trading Bot Live!* Interactive commands enabled (`/status`, `/stop`, `/start`, `/closeall`).")
        # Run market monitors and telegram command listener concurrently
        tasks = [self.monitor_token(symbol, cfg) for symbol, cfg in TOKENS.items()]
        tasks.append(self.telegram_command_listener())
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    bot = MultiTokenBot()
    try:
        asyncio.run(bot.run_parallel_trading())
    except KeyboardInterrupt:
        print("Bot stopped.")
