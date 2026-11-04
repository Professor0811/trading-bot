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


def fetch_vision_batch_prices() -> dict:
    """Unblocked Binance Vision batch fetch to seed and back up the WebSocket stream."""
    prices = {}
    try:
        res = requests.get("https://data-api.binance.vision/api/v3/ticker/price", timeout=4)
        if res.status_code == 200:
            data = res.json()
            lookup = {item["symbol"]: float(item["price"]) for item in data if "symbol" in item and "price" in item}
            for pair, b_sym in TOP_50_MAP.items():
                if b_sym in lookup and lookup[b_sym] > 0:
                    prices[pair] = lookup[b_sym]
    except Exception as e:
        print("[Vision Backup Error]:", e)
    return prices


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
        self.ws_connected = False
        self.latest_prices = {}
        self.price_history = {s: [] for s in TOP_50_MAP}

    async def handle_fast_tick(self, symbol: str, current_price: float):
        """
        Pure in-memory millisecond tick handler.
        Never makes blocking HTTP calls—only updates prices and triggers instant TP/SL exits.
        """
        self.latest_prices[symbol] = current_price
        history = self.price_history[symbol]
        if not history or history[-1] != current_price:
            history.append(current_price)
            if len(history) > 30:
                history.pop(0)

        # Instantaneous TP / SL / Trailing Stop / Liquidation check
        if symbol in self.engine.positions:
            closed = self.engine.check_exit_conditions_for_token(symbol, current_price)
            if closed:
                side_name = closed["side"]
                await asyncio.to_thread(
                    record_trade_db,
                    symbol,
                    "CLOSE_" + side_name,
                    closed["margin"],
                    closed["entry_price"],
                    closed["exit_price"],
                    closed["pnl"],
                    "CLOSED"
                )

                alert_msg = (
                    "🏁 *Real-Time WebSocket Exit (Slot Freed!)*\n"
                    "• Pair: `" + symbol + "` (" + side_name + " " + str(self.engine.leverage) + "x)\n"
                    "• Reason: `" + str(closed['reason']) + "`\n"
                    "• Entry Price: `$" + fmt_p(closed['entry_price']) + "`\n"
                    "• Exit Price: `$" + fmt_p(closed['exit_price']) + "`\n"
                    "• Net PnL: `$" + f"{closed['pnl']:+.2f}" + "`\n"
                    "• Wallet Balance: `$" + f"{self.engine.cash_balance:.2f}" + "`\n"
                    "• Active Slots: `" + str(len(self.engine.positions)) + "/" + str(self.engine.max_concurrent) + "`"
                )
                await asyncio.to_thread(send_telegram_alert, alert_msg)

    async def websocket_stream_listener(self):
        """
        Connects to US-unblocked Binance Vision WebSocket (`wss://data-stream.binance.vision`)
        with automatic failover.
        """
        endpoints = [
            "wss://data-stream.binance.vision/ws/!miniTicker@arr",
            "wss://stream.binance.com:9443/ws/!miniTicker@arr",
            "wss://fstream.binance.com/ws/!miniTicker@arr"
        ]
        idx = 0

        while self.is_running:
            uri = endpoints[idx % len(endpoints)]
            try:
                print("[WebSocket] Connecting to:", uri)
                async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
                    self.ws_connected = True
                    print("[WebSocket] Live stream active on:", uri)
                    await asyncio.to_thread(
                        send_telegram_alert,
                        "🔌 *WebSocket Stream Connected!*\n• Endpoint: `" + uri.split("/ws/")[0] + "`\n• Feed: Real-Time 50-Coin MiniTickers"
                    )

                    async for message in ws:
                        if not self.is_running:
                            break
                        data = json.loads(message)
                        if isinstance(data, list):
                            for item in data:
                                b_sym = item.get("s", "").lower()
                                price_str = item.get("c")
                                if b_sym in REVERSE_MAP and price_str:
                                    await self.handle_fast_tick(REVERSE_MAP[b_sym], float(price_str))
            except Exception as e:
                self.ws_connected = False
                print("[WebSocket Reconnecting]:", e)
                idx += 1
                await asyncio.sleep(3)

    async def klines_entry_scanner_loop(self):
        """
        Dedicated non-blocking scanner loop that ranks all 50 coins and evaluates
        15m Klines (Wilder's RSI + EMA) in background threads to fill all 5 slots.
        """
        print("[Klines Entry Scanner] Active and warming up...")

        while self.is_running:
            try:
                # Seed/refresh prices from Vision API so all 50 coins are immediately available
                batch_prices = await asyncio.to_thread(fetch_vision_batch_prices)
                for sym, price in batch_prices.items():
                    await self.handle_fast_tick(sym, price)

                # Check 10% Daily Drawdown Circuit Breaker
                if self.engine.is_circuit_breaker_triggered():
                    if not self.circuit_breaker_alerted:
                        self.trading_enabled = False
                        self.circuit_breaker_alerted = True
                        await asyncio.to_thread(
                            send_telegram_alert,
                            "🚨 *CIRCUIT BREAKER TRIGGERED!* Net loss reached 10%. Trading halted!"
                        )

                free_slots = self.engine.max_concurrent - len(self.engine.positions)
                if self.trading_enabled and free_slots > 0 and len(self.latest_prices) > 0:
                    # 1. Pre-rank coins by live price action so we evaluate the strongest movers first
                    pre_candidates = []
                    for symbol, current_price in list(self.latest_prices.items()):
                        if not self.engine.can_open_position(symbol):
                            continue
                        history = self.price_history.get(symbol, [])
                        if len(history) < 2:
                            continue

                        price_change_pct = abs((history[-1] - history[0]) / (history[0] + 1e-9)) * 100.0
                        trend = "UP" if history[-1] >= history[0] else "DOWN"
                        momentum = 0.85 if trend == "UP" else 0.35
                        pre_candidates.append({
                            "symbol": symbol,
                            "price": current_price,
                            "trend": trend,
                            "momentum": momentum,
                            "change_pct": price_change_pct
                        })

                    pre_candidates.sort(key=lambda x: x["change_pct"], reverse=True)

                    # 2. Evaluate top 15 movers using Real 15m Klines in a non-blocking thread
                    verified_picks = []
                    for cand in pre_candidates[:15]:
                        sym = cand["symbol"]
                        bin_sym = TOP_50_MAP.get(sym, "BTCUSDT")

                        signal = await asyncio.to_thread(
                            strategy_agent.evaluate_market,
                            cand["trend"],
                            50.0,
                            cand["momentum"],
                            1000000.0,
                            1.2,
                            0.6,
                            cand["price"],
                            bin_sym
                        )

                        if signal in ["LONG", "SHORT"]:
                            score = round((cand["change_pct"] * 50.0) + 60.0, 1)
                            verified_picks.append({
                                "symbol": sym,
                                "signal": signal,
                                "price": cand["price"],
                                "score": score
                            })
                            if len(verified_picks) >= free_slots:
                                break

                    # 3. Execute top verified setups up to free_slots
                    for pick in verified_picks[:free_slots]:
                        sym = pick["symbol"]
                        sig = pick["signal"]
                        cur_p = pick["price"]
                        score = pick["score"]

                        margin_amount = self.engine.calculate_position_size()
                        order_success = self.engine.execute_order(sym, sig, margin_amount, cur_p)

                        if order_success:
                            pos = self.engine.positions.get(sym, {})
                            entry_p = pos.get("entry_price", cur_p)
                            tp_p = pos.get("tp_price", entry_p)
                            sl_p = pos.get("sl_price", entry_p)
                            liq_p = pos.get("liq_price", entry_p)
                            leveraged_size = pos.get("leveraged_size", margin_amount * self.engine.leverage)

                            await asyncio.to_thread(
                                record_trade_db,
                                sym,
                                sig + "_" + str(self.engine.leverage) + "X",
                                margin_amount,
                                entry_p,
                                None,
                                0.0,
                                "OPEN"
                            )

                            side_emoji = "🟢" if sig == "LONG" else "🔴"
                            alert_msg = (
                                side_emoji + " *WebSocket + Klines " + str(self.engine.leverage) + "x Order (" + sig + ")*\n"
                                "• Pair: `" + sym + "` (Score: `" + str(score) + "`)\n"
                                "• Leverage: `" + str(self.engine.leverage) + "x Isolated`\n"
                                "• Entry Price: `$" + fmt_p(entry_p) + "`\n"
                                "• Margin (2%): `$" + f"{margin_amount:.2f}" + "` (Exposure: `$" + f"{leveraged_size:.2f}" + "`)\n"
                                "• Take-Profit Target: `$" + fmt_p(tp_p) + "`\n"
                                "• Stop-Loss Target: `$" + fmt_p(sl_p) + "`\n"
                                "• Est. Liq Price: `$" + fmt_p(liq_p) + "`\n"
                                "• Active Slots: `" + str(len(self.engine.positions)) + "/" + str(self.engine.max_concurrent) + "`\n"
                                "• Wallet Balance: `$" + f"{self.engine.cash_balance:.2f}" + "`"
                            )
                            await asyncio.to_thread(send_telegram_alert, alert_msg)

            except Exception as e:
                print("[Klines Entry Scanner Error]:", e)

            await asyncio.sleep(5)

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
                            ws_str = "ONLINE (WSS)" if self.ws_connected else "SYNCING (Vision)"
                            status_reply = (
                                "📊 *WebSocket + Klines Bot Status:*\n"
                                "• Engine State: " + state_str + "\n"
                                "• Stream Feed: " + ws_str + "\n"
                                "• Live Coins Synced: " + str(len(self.latest_prices)) + "/50\n"
                                "• Available Cash: $" + f"{self.engine.cash_balance:.2f}" + "\n"
                                "• Realized PnL: $" + f"{self.engine.realized_pnl:+.2f}" + "\n"
                                "• Active Slots: " + str(len(self.engine.positions)) + "/" + str(self.engine.max_concurrent) + "\n"
                                + pos_text
                            )
                            await asyncio.to_thread(send_telegram_alert, status_reply)

                        elif text == "/stop":
                            self.trading_enabled = False
                            await asyncio.to_thread(
                                send_telegram_alert,
                                "🛑 *Trading Paused!* WebSocket exits remain active, no new entries."
                            )

                        elif text == "/start":
                            self.trading_enabled = True
                            self.circuit_breaker_alerted = False
                            await asyncio.to_thread(
                                send_telegram_alert,
                                "▶️ *Trading Resumed!* WebSocket + Klines scanner active."
                            )

                        elif text == "/closeall":
                            closed_count = 0
                            for sym in list(self.engine.positions.keys()):
                                cur_p = self.latest_prices.get(sym, self.engine.positions[sym]["entry_price"])
                                closed = self.engine.check_exit_conditions_for_token(sym, cur_p)
                                if not closed:
                                    closed = self.engine._close_token_position(sym, "Manual /closeall", cur_p)
                                closed_count += 1
                            await asyncio.to_thread(
                                send_telegram_alert,
                                "⚠️ *Manual Exit Triggered!* Closed " + str(closed_count) + " position(s)."
                            )

            except Exception as e:
                print("[Telegram Listener Error]:", e)

            await asyncio.sleep(2)

    async def run_parallel_trading(self):
        await asyncio.to_thread(
            send_telegram_alert,
            "🚀 *Dual-Engine WebSocket + Klines Bot Online!*\n"
            "• Tick Stream: Binance Vision Real-Time WSS\n"
            "• Strategy Core: Non-Blocking 15m Klines (RSI + EMA)\n"
            "• Max Concurrent Slots: " + str(self.engine.max_concurrent)
        )
        await asyncio.gather(
            self.websocket_stream_listener(),
            self.klines_entry_scanner_loop(),
            self.telegram_command_listener()
        )


if __name__ == "__main__":
    bot = MultiTokenBot()
    try:
        asyncio.run(bot.run_parallel_trading())
    except KeyboardInterrupt:
        print("Bot stopped.")
