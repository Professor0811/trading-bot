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
        "binance_symbol": "SOLUSDT",
        "fallback": 93.50
    },
    "JUP/USDC": {
        "dex_url": "https://api.dexscreener.com/latest/dex/tokens/JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
        "binance_symbol": "JUPUSDT",
        "fallback": 1.05
    },
    "BONK/USDC": {
        "dex_url": "https://api.dexscreener.com/latest/dex/pairs/solana/DBrEeaP4o45m83q63rS5yHqU2X3uU1b47r1Z9xK6j6z",
        "binance_symbol": "1000BONKUSDT",
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
    """Fetch live market price via DexScreener with fallback to Binance."""
    try:
        res = requests.get(cfg["dex_url"], timeout=4)
        if res.status_code == 200:
            data = res.json()
            pairs = data.get("pairs") or ([data.get("pair")] if data.get("pair") else [])
            valid_pairs = [p for p in pairs if p and float(p.get("priceUsd", 0.0) or 0.0) > 0]
            if valid_pairs:
                top_pair = max(valid_pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0.0) or 0.0))
                price = float(top_pair["priceUsd"])
                liquidity = float(top_pair.get("liquidity", {}).get("usd", 50000.0) or 50000.0)
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
        self.engine = PaperTradingEngine(initial_capital=1000.0, max_concurrent=3)
        self.is_running = True
        self.trading_enabled = True
        self.circuit_breaker_alerted = False
        self.latest_prices = {}
        self.price_history = {s: [] for s in TOKENS}

    async def telegram_command_listener(self):
        """Poll Telegram for interactive control commands."""
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
                                active_desc.append(f"• `{sym}`: Entry ${fmt_p(p['entry_price'])} | TP ${fmt_p(p['tp_price'])}")
                            pos_text = "\n".join(active_desc) if active_desc else "None (0/3 Active)"

                            status_reply = (
                                f"📊 *Trading Bot Status (Max 3 Slots):*\n"
                                f"• Engine: `{'ACTIVE' if self.trading_enabled else 'PAUSED'}`\n"
                                f"• Real-Time Balance: `${self.engine.cash_balance:.2f}`\n"
                                f"• Realized PnL: `${self.engine.realized_pnl:+.2f}`\n"
                                f"• Active Slots: `{len(self.engine.positions)}/3`\n"
                                f"{pos_text}"
                            )
                            send_telegram_alert(status_reply)

                        elif text == "/stop":
                            self.trading_enabled = False
                            send_telegram_alert("🛑 *Trading Paused!* No new entries will be taken.")

                        elif text == "/start":
                            self.trading_enabled = True
                            self.circuit_breaker_alerted = False
                            send_telegram_alert("▶️ *Trading Resumed!* Slot manager & scanner active.")

                        elif text == "/closeall":
                            closed_count = 0
                            for sym in list(self.engine.positions.keys()):
                                cur_p = self.latest_prices.get(sym, self.engine.positions[sym]["entry_price"])
                                closed = self.engine.check_exit_conditions_for_token(sym, cur_p)
                                if not closed:
                                    closed = self.engine._close_token_position(sym, 0.0, "Manual /closeall", cur_p)
                                closed_count += 1
                            send_telegram_alert(f"⚠️ *Manual Exit Triggered!* Closed {closed_count} open position(s).")

            except Exception as e:
                print(f"[Telegram Listener Error]: {e}")

            await asyncio.sleep(2)

    async def monitor_token(self, symbol: str, cfg: dict):
        print(f"[{symbol}] Slot monitor active.")

        while self.is_running:
            try:
                # 1. Real-time market tick
                current_price, liquidity = await asyncio.to_thread(fetch_live_price, symbol, cfg)
                self.latest_prices[symbol] = current_price

                history = self.price_history[symbol]
                history.append(current_price)
                if len(history) > 20:
                    history.pop(0)

                # Technical momentum evaluation
                if len(history) >= 5:
                    momentum = 1.0 if history[-1] > history[-3] else 0.4
                    trend = "UP" if history[-1] >= history[0] else "DOWN"
                    spread = max(history) - min(history)
                    rsi = 50.0 + ((history[-1] - min(history)) / (spread + 1e-9) - 0.5) * 30.0
                else:
                    momentum = 1.0
                    trend = "UP"
                    rsi = 48.0

                # 2. Check 10% Daily Drawdown Circuit Breaker
                if self.engine.is_circuit_breaker_triggered():
                    if not self.circuit_breaker_alerted:
                        self.trading_enabled = False
                        self.circuit_breaker_alerted = True
                        send_telegram_alert(
                            "🚨 *CIRCUIT BREAKER TRIGGERED!* Daily net loss reached 10% of balance. Trading paused for safety!"
                        )

                # 3. Check Exits if this token has an open position
                if symbol in self.engine.positions:
                    closed = self.engine.check_exit_conditions_for_token(symbol, current_price)
                    if closed:
                        record_trade_db(
                            token_symbol=symbol,
                            action="SELL",
                            amount=closed["amount"],
                            entry_price=closed["entry_price"],
                            exit_price=closed["exit_price"],
                            pnl=closed["pnl"],
                            status="CLOSED"
                        )

                        alert_msg = (
                            f"🏁 *Position Closed (Slot Freed!)*\n"
                            f"• Pair: `{symbol}`\n"
                            f"• Reason: `{closed['reason']}`\n"
                            f"• Exit Price: `${fmt_p(closed['exit_price'])}`\n"
                            f"• Trade PnL: `${closed['pnl']:+.2f}`\n"
                            f"• New Balance: `${self.engine.cash_balance:.2f}`\n"
                            f"• Active Slots: `{len(self.engine.positions)}/3`"
                        )
                        send_telegram_alert(alert_msg)

                # 4. Check Entry if slot is available & trading enabled
                elif self.trading_enabled and self.engine.can_open_position(symbol):
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
                        trade_amount = self.engine.calculate_position_size()
                        order_success = self.engine.execute_order(symbol, "BUY", trade_amount, current_price)

                        if order_success:
                            pos = self.engine.positions.get(symbol, {})
                            entry_p = pos.get("entry_price", current_price)
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
                                f"🔔 *Real Market Order (Slot {len(self.engine.positions)}/3)*\n"
                                f"• Pair: `{symbol}`\n"
                                f"• Live Price: `${fmt_p(entry_p)}`\n"
                                f"• Position Size (2%): `${trade_amount:.2f}`\n"
                                f"• Take-Profit: `${fmt_p(tp_p)}`\n"
                                f"• Stop-Loss: `${fmt_p(sl_p)}`\n"
                                f"• Balance: `${self.engine.cash_balance:.2f}`"
                            )
                            send_telegram_alert(alert_msg)

            except Exception as err:
                print(f"[{symbol} Loop Error]: {err}")

            await asyncio.sleep(6)

    async def run_parallel_trading(self):
        send_telegram_alert(
            "🚀 *Autonomous Trading Bot Live!* Real-time prices synchronized.\n"
            "• 2% Dynamic Sizing\n"
            "• Max 3 Concurrent Slots\n"
            "• 10% Daily Circuit Breaker"
        )
        tasks = [self.monitor_token(symbol, cfg) for symbol, cfg in TOKENS.items()]
        tasks.append(self.telegram_command_listener())
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    bot = MultiTokenBot()
    try:
        asyncio.run(bot.run_parallel_trading())
    except KeyboardInterrupt:
        print("Bot stopped.")
