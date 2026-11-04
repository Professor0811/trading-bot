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
        self.latest_prices[symbol] = current_price
        history = self.price_history[symbol]
        if not history or history[-1] != current_price:
            history.append(current_price)
            if len(history) > 30:
                history.pop(0)

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
                    "🏁 *Real-Time Exit (Slot Freed!)*\n"
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
        endpoints = [
            "wss://data-stream.binance.vision/ws/!miniTicker@arr",
            "wss://stream.binance.com:9443/ws/!miniTicker@arr"
        ]
        idx = 0

        while self.is_running:
            uri = endpoints[idx % len(endpoints)]
            try:
                async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
                    self.ws_connected = True
                    await asyncio.to_thread(
                        send_telegram_alert,
                        "🔌 *WebSocket Stream Connected!*\n• Feed: Real-Time Binance Vision WSS"
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
            except Exception:
                self.ws_connected = False
                idx += 1
                await asyncio.sleep(3)

    async def klines_entry_scanner_loop(self):
        while self.is_running:
            try:
                batch_prices = await asyncio.to_thread(fetch_vision_batch_prices)
                for sym, price in batch_prices.items():
                    await self.handle_fast_tick(sym, price)

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
                    pre_candidates = []
                    for symbol, current_price in list(self.latest_prices.items()):
                        if not self.engine.can_open_position(symbol):
                            continue
                        history = self.price_history.get(symbol, [])
                        if len(history) < 2:
                            continue

                        price_change_pct = abs((history[-1] - history[0]) / (history[0] + 1e-9)) * 100.0
                        trend = "UP" if history[-1] >= history[0] else "DOWN"
                        pre_candidates.append({
                            "symbol": symbol,
                            "price": current_price,
                            "trend": trend,
                            "change_pct": price_change_pct
                        })

                    pre_candidates.sort(key=lambda x: x["change_pct"], reverse=True)

                    # Evaluate top movers using 15m Klines + 1H Macro Trend + Volume Spike + Dynamic ATR
                    verified_picks = []
                    for cand in pre_candidates[:20]:
                        sym = cand["symbol"]
                        bin_sym = TOP_50_MAP.get(sym, "BTCUSDT")

                        signal, atr_val, vol_ratio, macro_trend = await asyncio.to_thread(
                            strategy_agent.evaluate_market_with_atr,
                            cand["trend"],
                            cand["price"],
                            bin_sym
                        )

                        if signal in ["LONG", "SHORT"]:
                            vol_bonus = min(30.0, (vol_ratio - 1.0) * 20.0)
                            score = round((cand["change_pct"] * 40.0) + 60.0 + vol_bonus, 1)
                            verified_picks.append({
                                "symbol": sym,
                                "signal": signal,
                                "price": cand["price"],
                                "score": score,
                                "atr": atr_val,
                                "vol_ratio": vol_ratio,
                                "macro_trend": macro_trend
                            })
                            if len(verified_picks) >= free_slots:
                                break

                    verified_picks.sort(key=lambda x: x["score"], reverse=True)

                    for pick in verified_picks[:free_slots]:
                        sym = pick["symbol"]
                        sig = pick["signal"]
                        cur_p = pick["price"]
                        score = pick["score"]
                        atr = pick["atr"]
                        v_ratio = pick["vol_ratio"]
                        m_trend = pick["macro_trend"]

                        margin_amount = self.engine.calculate_position_size()
                        order_success = self.engine.execute_order(sym, sig, margin_amount, cur_p, custom_atr=atr)

                        if order_success:
                            pos = self.engine.positions.get(sym, {})
                            entry_p = pos.get("entry_price", cur_p)
                            tp_p = pos.get("tp_price", entry_p)
                            sl_p = pos.get("sl_price", entry_p)
                            liq_p = pos.get("liq_price", entry_p)

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
                                side_emoji + " *MTF + Volume " + str(self.engine.leverage) + "x Order (" + sig + ")*\n"
                                "• Pair: `" + sym + "` (Score: `" + str(score) + "`)\n"
                                "• Macro Alignment: `" + m_trend + " + 15m " + sig + "` 🧭\n"
                                "• Volume Spike: `" + f"{v_ratio:.2f}x" + " Avg Vol` 🔥\n"
                                "• Entry Price: `$" + fmt_p(entry_p) + "`\n"
                                "• Dynamic SL (1.5x ATR): `$" + fmt_p(sl_p) + "`\n"
                                "• Dynamic TP (3.0x ATR): `$" + fmt_p(tp_p) + "`\n"
                                "• Est. Liq Price: `$" + fmt_p(liq_p) + "`\n"
                                "• Active Slots: `" + str(len(self.engine.positions)) + "/" + str(self.engine.max_concurrent) + "`\n"
                                "• Wallet Balance: `$" + f"{self.engine.cash_balance:.2f}" + "`"
                            )
                            await asyncio.to_thread(send_telegram_alert, alert_msg)

            except Exception as e:
                print("[Klines Scanner Error]:", e)

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
                                sl_str = fmt_p(p["sl_price"])
                                side_str = p["side"]
                                margin_str = f"{p['margin']:.2f}"
                                line = "• " + sym + " (" + side_str + " " + str(self.engine.leverage) + "x): Margin $" + margin_str + " | Entry $" + entry_str + " | SL $" + sl_str + " | TP $" + tp_str
                                active_desc.append(line)
                            pos_text = "\n".join(active_desc) if active_desc else "None (0/5 Active Slots)"

                            state_str = "ACTIVE" if self.trading_enabled else "PAUSED"
                            ws_str = "ONLINE (WSS)" if self.ws_connected else "SYNCING (Vision)"
                            status_reply = (
                                "📊 *MTF + Volume ATR Bot Status:*\n"
                                "• Engine State: " + state_str + "\n"
                                "• Stream Feed: " + ws_str + "\n"
                                "• Live Tracked Coins: " + str(len(self.latest_prices)) + "/50\n"
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
                                "🛑 *Trading Paused!* Exits remain active, no new entries."
                            )

                        elif text == "/start":
                            self.trading_enabled = True
                            self.circuit_breaker_alerted = False
                            await asyncio.to_thread(
                                send_telegram_alert,
                                "▶️ *Trading Resumed!* MTF + Volume Engine active."
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
            "🚀 *Upgrade 2 Complete: Multi-Timeframe (1H + 15m) Engine Online!*\n"
            "• Macro Filter: 1H EMA 20/50 Trend Alignment\n"
            "• Micro Filter: 15m Wilder's RSI + Volume Spike (>=1.10x)\n"
            "• Risk: Dynamic ATR (1.5x SL / 3.0x TP)"
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
