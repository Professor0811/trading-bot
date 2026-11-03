import asyncio
import sqlite3
import os
import json
import requests
import websockets
from datetime import datetime
import config
import risk_manager
import strategy_agent
from paper_engine import PaperTradingEngine
from telegram_alerts import send_telegram_alert

DB_PATH = os.environ.get("TRADING_BOT_DB", "trading_bot.db")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Top 50 High-Liquidity Binance Futures Pairs mapping
TOP_50_MAP = {
    "BTC/USDC": "BTCUSDT", "ETH/USDC": "ETHUSDT", "SOL/USDC": "SOLUSDT",
    "BNB/USDC": "BNBUSDT", "XRP/USDC": "XRPUSDT", "DOGE/USDC": "DOGEUSDT",
    "ADA/USDC": "ADAUSDT", "AVAX/USDC": "AVAXUSDT", "TRX/USDC": "TRXUSDT",
    "LINK/USDC": "LINKUSDT", "DOT/USDC": "DOTUSDT", "NEAR/USDC": "NEARUSDT",
    "SUI/USDC": "SUIUSDT", "MATIC/USDC": "POLUSDT", "LTC/USDC": "LTCUSDT",
    "ICP/USDC": "ICPUSDT", "UNI/USDC": "UNIUSDT", "APT/USDC": "APTUSDT",
    "PEPE/USDC": "PEPEUSDT", "SHIB/USDC": "SHIBUSDT", "FET/USDC": "FETUSDT",
    "ETC/USDC": "ETCUSDT", "STX/USDC": "STXUSDT", "FIL/USDC": "FILUSDT",
    "RENDER/USDC": "RENDERUSDT", "ATOM/USDC": "ATOMUSDT", "ARB/USDC": "ARBUSDT",
    "IMX/USDC": "IMXUSDT", "WIF/USDC": "WIFUSDT", "OP/USDC": "OPUSDT",
    "INJ/USDC": "INJUSDT", "HBAR/USDC": "HBARUSDT", "BONK/USDC": "BONKUSDT",
    "VET/USDC": "VETUSDT", "GRT/USDC": "GRTUSDT", "TAO/USDC": "TAOUSDT",
    "SEI/USDC": "SEIUSDT", "FLOKI/USDC": "FLOKIUSDT", "JUP/USDC": "JUPUSDT",
    "RUNE/USDC": "RUNEUSDT", "TIA/USDC": "TIAUSDT", "ALGO/USDC": "ALGOUSDT",
    "AAVE/USDC": "AAVEUSDT", "PYTH/USDC": "PYTHUSDT", "MKR/USDC": "MKRUSDT",
    "GALA/USDC": "GALAUSDT", "FLOW/USDC": "FLOWUSDT", "DYDX/USDC": "DYDXUSDT",
    "ORDI/USDC": "ORDIUSDT", "PENDLE/USDC": "PENDLEUSDT"
}

REVERSE_MAP = {v.lower(): k for k, v in TOP_50_MAP.items()}


def fmt_p(val: float) -> str:
    if val is None:
        return "0.00"
    val = float(val)
    if val < 0.0001:
        return f"{val:.8f}".rstrip("0").rstrip(".")
    elif val < 1.0:
        return f"{val:.6f}"
    return f"{val:.4f}"


def record_trade_db(token_symbol, action, amount, entry_price, exit_price=None, pnl=0.0, status="OPEN"):
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
        print("[DB Error]:", e)


class MultiTokenBot:
    def __init__(self):
        self.engine = PaperTradingEngine(
            initial_capital=config.STARTING_CAPITAL,
            max_concurrent=5
        )
        self.is_running = True
        self.trading_enabled = True
        self.circuit_breaker_alerted = False
        self.latest_prices = {}
        self.price_history = {s: [] for s in TOP_50_MAP}

    async def telegram_command_listener(self):
        if not BOT_TOKEN:
            return

        last_update_id = 0
        url = "https://api.telegram.org/bot" + BOT_TOKEN + "/getUpdates"

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
                                entry_str = fmt_p(p["entry_price"])
                                tp_str = fmt_p(p["tp_price"])
                                side_str = p["side"]
                                margin_str = f"{p['margin']:.2f}"
                                line = "• " + sym + " (" + side_str + " " + str(self.engine.leverage) + "x): Margin $" + margin_str + " | Entry $" + entry_str + " | TP $" + tp_str
                                active_desc.append(line)
                            pos_text = "\n".join(active_desc) if active_desc else "None (0/5 Active Slots)"

                            state_str = "ACTIVE" if self.trading_enabled else "PAUSED"
                            status_reply = (
                                "📊 *WebSocket-Engine Status (5 Slots):*\n"
                                "• Engine State: " + state_str + "\n"
                                "• Live Tracked Coins: " + str(len(self.latest_prices)) + "/50\n"
                                "• Available Cash: $" + f"{self.engine.cash_balance:.2f}" + "\n"
                                "• Realized PnL: $" + f"{self.engine.realized_pnl:+.2f}" + "\n"
                                "• Active Slots: " + str(len(self.engine.positions)) + "/" + str(self.engine.max_concurrent) + "\n"
                                + pos_text
                            )
                            send_telegram_alert(status_reply)

                        elif text == "/stop":
                            self.trading_enabled = False
                            send_telegram_alert("🛑 *Trading Paused!* WebSocket stream active, but no new positions will be opened.")

                        elif text == "/start":
                            self.trading_enabled = True
                            self.circuit_breaker_alerted = False
                            send_telegram_alert("▶️ *Trading Resumed!* Real-time WebSocket engine active.")

                        elif text == "/closeall":
                            closed_count = 0
                            for sym in list(self.engine.positions.keys()):
                                cur_p = self.latest_prices.get(sym, self.engine.positions[sym]["entry_price"])
                                closed = self.engine.check_exit_conditions_for_token(sym, cur_p)
                                if not closed:
                                    closed = self.engine._close_token_position(sym, "Manual /closeall", cur_p)
                                closed_count += 1
                            send_telegram_alert("⚠️ *Manual Exit Triggered!* Closed " + str(closed_count) + " position(s).")

            except Exception as e:
                print("[Telegram Listener Error]:", e)

            await asyncio.sleep(2)

    async def process_tick(self, symbol: str, current_price: float):
        try:
            self.latest_prices[symbol] = current_price
            history = self.price_history[symbol]
            history.append(current_price)
            if len(history) > 20:
                history.pop(0)

            # 1. Check Circuit Breaker
            if self.engine.is_circuit_breaker_triggered():
                if not self.circuit_breaker_alerted:
                    self.trading_enabled = False
                    self.circuit_breaker_alerted = True
                    send_telegram_alert("🚨 *CIRCUIT BREAKER TRIGGERED!* Net loss reached 10%. Trading halted!")

            # 2. Check Exits if position is open
            if symbol in self.engine.positions:
                closed = self.engine.check_exit_conditions_for_token(symbol, current_price)
                if closed:
                    side_name = closed["side"]
                    record_trade_db(
                        token_symbol=symbol,
                        action="CLOSE_" + side_name,
                        amount=closed["margin"],
                        entry_price=closed["entry_price"],
                        exit_price=closed["exit_price"],
                        pnl=closed["pnl"],
                        status="CLOSED"
                    )

                    alert_msg = (
                        "🏁 *Futures Position Closed (Slot Freed!)*\n"
                        "• Pair: `" + symbol + "` (" + side_name + " " + str(self.engine.leverage) + "x)\n"
                        "• Reason: `" + str(closed['reason']) + "`\n"
                        "• Entry Price: `$" + fmt_p(closed['entry_price']) + "`\n" "• Exit Price: `$" + fmt_p(closed['exit_price']) + "`\n"
                        "• Net PnL: `$" + f"{closed['pnl']:+.2f}" + "`\n" "• Wallet Balance: `$" + f"{self.engine.cash_balance:.2f}" + "`\n"
                        "• Active Slots: `" + str(len(self.engine.positions)) + "/" + str(self.engine.max_concurrent) + "`"
                    )
                    send_telegram_alert(alert_msg)

            # 3. Check Entries if slots are available
            free_slots = self.engine.max_concurrent - len(self.engine.positions)
            if self.trading_enabled and free_slots > 0 and self.engine.can_open_position(symbol):
                if len(history) >= 2:
                    price_change_pct = abs((history[-1] - history[0]) / (history[0] + 1e-9)) * 100.0
                    trend = "UP" if history[-1] >= history[0] else "DOWN"
                    momentum = 0.85 if trend == "UP" else 0.35

                    bin_sym = TOP_50_MAP.get(symbol, "BTCUSDT")
                    signal = strategy_agent.evaluate_market(
                        trend=trend,
                        rsi=50.0,
                        momentum=momentum,
                        liquidity_usd=1000000.0,
                        macd=1.2,
                        macd_signal=0.6,
                        price=current_price,
                        binance_symbol=bin_sym
                    )

                    if signal in ["LONG", "SHORT"]:
                        conviction_score = round((price_change_pct * 40.0) + 50.0, 1)
                        margin_amount = self.engine.calculate_position_size()
                        order_success = self.engine.execute_order(symbol, signal, margin_amount, current_price)

                        if order_success:
                            pos = self.engine.positions.get(symbol, {})
                            entry_p = pos.get("entry_price", current_price)
                            tp_p = pos.get("tp_price", entry_p)
                            sl_p = pos.get("sl_price", entry_p)
                            liq_p = pos.get("liq_price", entry_p)
                            leveraged_size = pos.get("leveraged_size", margin_amount * self.engine.leverage)

                            record_trade_db(
                                token_symbol=symbol,
                                action=signal + "_" + str(self.engine.leverage) + "X",
                                amount=margin_amount,
                                entry_price=entry_p,
                                status="OPEN"
                            )

                            side_emoji = "🟢" if signal == "LONG" else "🔴"
                            alert_msg = (
                                side_emoji + " *WebSocket Real-Time " + str(self.engine.leverage) + "x Order (" + signal + ")*\n"
                                "• Pair: `" + symbol + "` (Score: `" + str(conviction_score) + "`)\n"
                                "• Leverage: `" + str(self.engine.leverage) + "x Isolated`\n"
                                "• Entry Price: `$" + fmt_p(entry_p) + "`\n" "• Margin (2\%): `$" + f"{margin_amount:.2f}" + "` (Exposure: `$" + f"{leveraged_size:.2f}`)\n" "• Take-Profit Target: `$" + fmt_p(tp_p) + "`\n"
                                "• Stop-Loss Target: `$" + fmt_p(sl_p) + "`\n" "• Est. Liq Price: `$" + fmt_p(liq_
