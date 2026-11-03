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

# Top 50 High-Liquidity Binance Futures/Spot Pairs
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


def fmt_p(val: float) -> str:
    if val is None:
        return "0.00"
    val = float(val)
    if val < 0.0001:
        return f"{val:.8f}".rstrip("0").rstrip(".")
    elif val < 1.0:
        return f"{val:.6f}"
    return f"{val:.4f}"


def fetch_all_binance_prices() -> dict:
    """
    Single-call batch fetch for all 50 coins.
    Uses data-api.binance.vision (No US IP blocking on Render) with Bybit fallback.
    """
    prices = {}
    endpoints = [
        "https://data-api.binance.vision/api/v3/ticker/price",
        "https://api.binance.com/api/v3/ticker/price",
        "https://api1.binance.com/api/v3/ticker/price"
    ]

    for url in endpoints:
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    binance_lookup = {item["symbol"]: float(item["price"]) for item in data if "symbol" in item and "price" in item}
                    for pair, b_sym in TOP_50_MAP.items():
                        if b_sym in binance_lookup and binance_lookup[b_sym] > 0:
                            prices[pair] = binance_lookup[b_sym]
                    if len(prices) >= 10:
                        return prices
            else:
                print("[Ticker Warning] Status", res.status_code, "from", url)
        except Exception as e:
            print("[Batch Ticker Error]:", e)

    # Secondary Fallback: Bybit V5 Spot Tickers (if Binance vision is unreachable)
    try:
        res = requests.get("https://api.bybit.com/v5/market/tickers?category=spot", timeout=5)
        if res.status_code == 200:
            items = res.json().get("result", {}).get("list", [])
            bybit_lookup = {item["symbol"]: float(item["lastPrice"]) for item in items if "symbol" in item and "lastPrice" in item}
            for pair, b_sym in TOP_50_MAP.items():
                if b_sym in bybit_lookup and bybit_lookup[b_sym] > 0:
                    prices[pair] = bybit_lookup[b_sym]
    except Exception as e:
        print("[Bybit Fallback Error]:", e)

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
                                "📊 *50-Coin Scanner Status (5 Slots):*\n"
                                "• Engine State: " + state_str + "\n"
                                "• Coins Synced: " + str(len(self.latest_prices)) + "/50\n"
                                "• Available Cash: $" + f"{self.engine.cash_balance:.2f}" + "\n"
                                "• Realized PnL: $" + f"{self.engine.realized_pnl:+.2f}" + "\n"
                                "• Active Slots: " + str(len(self.engine.positions)) + "/" + str(self.engine.max_concurrent) + "\n"
                                + pos_text
                            )
                            send_telegram_alert(status_reply)

                        elif text == "/stop":
                            self.trading_enabled = False
                            send_telegram_alert("🛑 *Trading Paused!* 50-Coin scanner will not open new positions.")

                        elif text == "/start":
                            self.trading_enabled = True
                            self.circuit_breaker_alerted = False
                            send_telegram_alert("▶️ *Trading Resumed!* 50-Coin Ranking Engine active.")

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

    async def batch_scanner_loop(self):
        print("[Batch Scanner] Monitoring Top 50 Coins -> Picking Best 5...")

        while self.is_running:
            try:
                # 1. Fetch all 50 coin prices in a single unblocked API call
                batch_prices = await asyncio.to_thread(fetch_all_binance_prices)
                if not batch_prices:
                    print("[Batch Scanner] No prices returned, retrying...")
                    await asyncio.sleep(4)
                    continue

                # 2. Check Circuit Breaker
                if self.engine.is_circuit_breaker_triggered():
                    if not self.circuit_breaker_alerted:
                        self.trading_enabled = False
                        self.circuit_breaker_alerted = True
                        send_telegram_alert("🚨 *CIRCUIT BREAKER TRIGGERED!* Net loss reached 10%. Trading halted!")

                # 3. Update price history & check exits for currently open positions first
                for symbol, current_price in batch_prices.items():
                    self.latest_prices[symbol] = current_price
                    history = self.price_history[symbol]
                    history.append(current_price)
                    if len(history) > 20:
                        history.pop(0)

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
                                "• Entry Price: `$" + fmt_p(closed['entry_price']) + "`\n"
                                "• Exit Price: `$" + fmt_p(closed['exit_price']) + "`\n"
                                "• Net PnL: `$" + f"{closed['pnl']:+.2f}" + "`\n"
                                "• Wallet Balance: `$" + f"{self.engine.cash_balance:.2f}" + "`\n"
                                "• Active Slots: `" + str(len(self.engine.positions)) + "/" + str(self.engine.max_concurrent) + "`"
                            )
                            send_telegram_alert(alert_msg)

                # 4. Scan & Rank Top Candidates if slots are available
                free_slots = self.engine.max_concurrent - len(self.engine.positions)
                if self.trading_enabled and free_slots > 0:
                    candidates = []

                    for symbol, current_price in batch_prices.items():
                        if not self.engine.can_open_position(symbol):
                            continue

                        history = self.price_history[symbol]
                        if len(history) < 2:
                            continue

                        # Calculate Trend, RSI, and Conviction Score
                        price_change_pct = abs((history[-1] - history[0]) / (history[0] + 1e-9)) * 100.0
                        trend = "UP" if history[-1] >= history[0] else "DOWN"
                        momentum = 0.85 if trend == "UP" else 0.35
                        spread = max(history) - min(history)
                        if spread > 0:
                            rsi = 45.0 + ((history[-1] - min(history)) / spread - 0.5) * 20.0
                        else:
                            rsi = 48.0 if trend == "UP" else 52.0

                        signal = strategy_agent.evaluate_market(
                            trend=trend,
                            rsi=rsi,
                            momentum=momentum,
                            liquidity_usd=1000000.0,
                            macd=1.2,
                            macd_signal=0.6,
                            price=current_price
                        )

                        if signal in ["LONG", "SHORT"]:
                            rsi_bonus = (70.0 - rsi) if signal == "LONG" else (rsi - 30.0)
                            conviction_score = round((price_change_pct * 50.0) + max(10.0, rsi_bonus), 1)
                            candidates.append({
                                "symbol": symbol,
                                "signal": signal,
                                "price": current_price,
                                "score": conviction_score
                            })

                    # Sort candidates by highest Conviction Score and pick best N for free slots
                    candidates.sort(key=lambda x: x["score"], reverse=True)
                    top_picks = candidates[:free_slots]

                    for pick in top_picks:
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

                            record_trade_db(
                                token_symbol=sym,
                                action=sig + "_" + str(self.engine.leverage) + "X",
                                amount=margin_amount,
                                entry_price=entry_p,
                                status="OPEN"
                            )

                            side_emoji = "🟢" if sig == "LONG" else "🔴"
                            alert_msg = (
                                side_emoji + " *Top-Ranked " + str(self.engine.leverage) + "x Order (" + sig + ")*\n"
                                "• Pair: `" + sym + "` (Rank Score: `" + str(score) + "`)\n"
                                "• Leverage: `" + str(self.engine.leverage) + "x Isolated`\n"
                                "• Entry Price: `$" + fmt_p(entry_p) + "`\n"
                                "• Margin (2%): `$" + f"{margin_amount:.2f}" + "` (Exposure: `$" + f"{leveraged_size:.2f}" + "`)\n"
                                "• Take-Profit Target: `$" + fmt_p(tp_p) + "`\n"
                                "• Stop-Loss Target: `$" + fmt_p(sl_p) + "`\n"
                                "• Est. Liq Price: `$" + fmt_p(liq_p) + "`\n"
                                "• Active Slots: `" + str(len(self.engine.positions)) + "/" + str(self.engine.max_concurrent) + "`\n"
                                "• Wallet Balance: `$" + f"{self.engine.cash_balance:.2f}" + "`"
                            )
                            send_telegram_alert(alert_msg)

            except Exception as err:
                print("[Batch Scanner Loop Error]:", err)

            await asyncio.sleep(6)

    async def run_parallel_trading(self):
        send_telegram_alert(
            "🚀 *50-Coin Batch Scanner & Ranking Bot Online!*\n"
            "• Scanned Universe: Top 50 Binance Vision Pairs\n"
            "• Execution Mode: Best 5 Setups (Ranked by Score)\n"
            "• Leverage: " + str(self.engine.leverage) + "x Isolated Margin\n"
            "• Max Concurrent Slots: " + str(self.engine.max_concurrent)
        )
        await asyncio.gather(
            self.batch_scanner_loop(),
            self.telegram_command_listener()
        )


if __name__ == "__main__":
    bot = MultiTokenBot()
    try:
        asyncio.run(bot.run_parallel_trading())
    except KeyboardInterrupt:
        print("Bot stopped.")
