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
    Primary: Binance Official Ticker (Rock solid, no DEX spikes).
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
                # Sanity check: SOL cannot be $200 when market is around $93
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
                                    f"• `{sym}` ({p['side']} 5x): Margin ${p['margin']:.2f} | "
                                    f"Entry ${fmt_p(p['entry_price'])} | TP ${fmt_p(p['tp_price'])}"
                                )
                            pos_text = "\n".join(active_desc) if active_desc else "None (0/3 Active Slots)"

                            status_reply = (
                                f"📊 *5x Futures Bot Status (3 Slots):*\n"
                                f"• Engine State: `{'ACTIVE' if self.trading_enabled else 'PAUSED'}`\n"
                                f"• Available Cash: `${self.engine.cash_balance:.2f}`\n"
                                f"• Realized PnL: `${self.engine.realized_pnl:+.2f}`\n"
                                f"• Active Slots: `{len(self.engine.positions)}/{self.engine.max_concurrent}`\n"
                                f"{pos_text}"
                            )
                            send_telegram_alert(status_reply)

                        elif text == "/stop":
                            self.trading_enabled = False
                            send_telegram_alert("🛑 *Trading Paused!* No new Futures positions will be opened.")

                        elif text == "/start":
                            self.trading_enabled = True
                            self.circuit_breaker_alerted = False
                            send_telegram_alert("▶️ *Trading Resumed!* Real Binance price scanner active.")

                        elif text == "/closeall":
                            closed_count = 0
                            for sym in list(self.engine.positions.keys()):
                                cur_p = self.latest_prices.get(sym, self.engine.positions[sym]["entry_price"])
                                closed = self.engine.check_exit_conditions_for_token(sym, cur_p)
                                if not closed:
                                    closed = self.engine._close_token_position(sym, "Manual /closeall", cur_p)
                                closed_count += 1
                            send_telegram_alert(f"⚠️ *Manual Exit Triggered!* Closed {closed_count} position(s).")

            except Exception as e:
                print(f"[Telegram Listener Error]: {e}")

            await asyncio.sleep(2)

    async def monitor_token(self, symbol: str, cfg: dict):
        print(f"[{symbol}] Real-price monitor online.")

        while self.is_running:
            try:
                # 1. Fetch exact live market tick (Binance Primary)
                current_price, liquidity = await asyncio.to_thread(fetch_live_price, symbol, cfg)
                self.latest_prices[symbol] = current_price

                history = self.price_history[symbol]
                history.append(current_price)
                if len(history) > 20:
                    history.pop(0)

                # Technical momentum and trend evaluation
                if len(history) >= 5:
                    momentum = 0.85 if history[-1] > history[-3] else 0.35
                    trend = "UP" if history[-1] >= history[0] else "DOWN"
                    spread = max(history) - min(history)
                    rsi = 50.0 + ((history[-1] - min(history)) / (spread + 1e-9) - 0.5) * 30.0
                else:
                    momentum = 0.8
                    trend = "UP"
                    rsi = 48.0

                # 2. Check 10% Daily Drawdown Circuit Breaker
                if self.engine.is_circuit_breaker_triggered():
                    if not self.circuit_breaker_alerted:
                        self.trading_enabled = False
                        self.circuit_breaker_alerted = True
                        send_telegram_alert(
                            "🚨 *CIRCUIT BREAKER TRIGGERED!* Daily net loss reached 10% of balance. Trading halted for safety!"
                        )

                # 3. Check Exits if position is open
                if symbol in self.engine.positions:
                    closed = self.engine.check_exit_conditions_for_token(symbol, current_price)
                    if closed:
                        side_name = closed["side"]
                        record_trade_db(
                            token_symbol=symbol,
                            action=f"CLOSE_{side_name}",
                            amount=closed["margin"],
                            entry_price=closed["entry_price"],
                            exit_price=closed["exit_price"],
                            pnl=closed["pnl"],
                            status="CLOSED"
                        )

                        alert_msg = (
                            f"🏁 *Futures Position Closed (Slot Freed!)*\n"
                            f"• Pair: `{symbol}` ({side_name} 5x)\n"
                            f"• Reason: `{closed['reason']}`\n"
                            f"• Entry Price: `${fmt_p(closed['entry_price'])}`\n"
                            f"• Exit Price: `${fmt_p(closed['exit_price'])}`\n"
                            f"• Net PnL: `${closed['pnl']:+.2f}`\n"
                            f"• Wallet Balance: `${self.engine.cash_balance:.2f}`\n"
                            f"• Active Slots: `{len(self.engine.positions)}/{self.engine.max_concurrent}`"
                        )
                        send_telegram_alert(alert_msg)

                # 4. Check Bi-Directional Entry (LONG or SHORT)
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

                    if signal in ["LONG", "SHORT"]:
                        margin_amount = self.engine.calculate_position_size()
                        order_success = self.engine.execute_order(symbol, signal, margin_amount, current_price)

                        if order_success:
                            pos = self.engine.positions.get(symbol, {})
                            entry_p = pos.get("entry_price", current_price)
                            tp_p = pos.get("tp_price", entry_p)
                            sl_p = pos.get("sl_price", entry_p)
                            liq_p = pos.get("liq_price", entry_p)
                            leveraged_size = pos.get("leveraged_size", margin_amount * 5)

                            record_trade_db(
                                token_symbol=symbol,
                                action=f"{signal}_5X",
                                amount=margin_amount,
                                entry_price=entry_p,
                                status="OPEN"
                            )

                            side_emoji = "🟢" if signal == "LONG" else "🔴"
                            alert_msg = (
                                f"{side_emoji} *New 5x Futures Order ({signal})*\n"
                                f"• Pair: `{symbol}`\n"
                                f"• Leverage: `5x Isolated`\n"
                                f"• Entry Price: `${fmt_p(entry_p)}`\n"
                                f"• Margin (2%): `${margin_amount:.2f}` (Exposure: `${leveraged_size:.2f}`)\n"
                                f"• Take-Profit Target: `${fmt_p(tp_p)}` (+15% ROE)\n"
                                f"• Stop-Loss Target: `${fmt_p(sl_p)}` (-6% Loss)\n"
                                f"• Est. Liq Price: `${fmt_p(liq_p)}`\n"
                                f"• Wallet Balance: `${self.engine.cash_balance:.2f}`"
                            )
                            send_telegram_alert(alert_msg)

            except Exception as err:
                print(f"[{symbol} Loop Error]: {err}")

            await asyncio.sleep(6)

    async def run_parallel_trading(self):
        send_telegram_alert(
            "🚀 *Autonomous 5x Futures Bot: Binance Price Feed Synced!*\n"
            "• Mode: Long & Short (Bi-Directional)\n"
            "• Primary Feed: Binance Real-Time Ticker\n"
            "• Zero Off-Market Spikes"
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
