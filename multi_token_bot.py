import asyncio
import os
import requests
from datetime import datetime
import config
import strategy_agent
import database
import bot_bridge
from bybit_connector import bybit_client
from paper_engine import PaperTradingEngine
from telegram_alerts import send_telegram_alert

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def fmt_p(val: float) -> str:
    if val is None:
        return "0.00"
    val = float(val)
    if val < 0.0001:
        return f"{val:.8f}".rstrip("0").rstrip(".")
    elif val < 1.0:
        return f"{val:.6f}"
    return f"{val:.4f}"


class MultiTokenBot:
    def __init__(self):
        self.engine = PaperTradingEngine(
            initial_capital=config.STARTING_CAPITAL,
            max_concurrent=config.MAX_CONCURRENT_TRADES,
            max_same_side=config.MAX_SAME_SIDE_TRADES
        )
        self.is_running = True
        self.trading_enabled = True
        self.circuit_breaker_alerted = False
        self.latest_prices = {}
        self.price_history = {}
        self.market_radar = []
        self.btc_regime = {"regime": "STABLE", "allow_long": True, "allow_short": True, "reason": "System Initializing"}
        self.last_crash_alert_time = 0

    async def handle_fast_tick(self, symbol: str, current_price: float):
        self.latest_prices[symbol] = current_price
        if symbol not in self.price_history:
            self.price_history[symbol] = []
        history = self.price_history[symbol]
        if not history or history[-1] != current_price:
            history.append(current_price)
            if len(history) > 30:
                history.pop(0)

        if symbol in self.engine.positions:
            event = self.engine.check_exit_conditions_for_token(symbol, current_price)
            if event:
                side_name = event["side"]
                event_type = event.get("event_type", "FULL")

                if event_type == "PARTIAL":
                    await asyncio.to_thread(
                        database.record_trade,
                        symbol,
                        "PARTIAL_50%_" + side_name,
                        event["closed_margin"],
                        event["entry_price"],
                        event["exit_price"],
                        event["pnl"],
                        "CLOSED"
                    )

                    alert_msg = (
                        "💰 *50% Partial Take-Profit + Auto Break-Even!*\n"
                        "• Exchange: `Bybit V5 Linear (Hybrid)` ⚡\n"
                        "• Pair: `" + symbol + "` (" + side_name + " " + str(self.engine.leverage) + "x)\n"
                        "• Milestone: `+1.5x ATR Reached` 🎯\n"
                        "• Entry Price: `$" + fmt_p(event['entry_price']) + "`\n"
                        "• Scale-Out Price: `$" + fmt_p(event['exit_price']) + "`\n"
                        "• Locked Profit (50%): `$" + f"{event['pnl']:+.2f}" + "`\n"
                        "• New Stop-Loss: `$" + fmt_p(event['new_sl_price']) + " (Break-Even 🛡️)`\n"
                        "• Wallet Balance: `$" + f"{self.engine.cash_balance:.2f}" + "`"
                    )
                    await asyncio.to_thread(send_telegram_alert, alert_msg)

                else:
                    await asyncio.to_thread(
                        database.record_trade,
                        symbol,
                        "CLOSE_" + side_name,
                        event["margin"],
                        event["entry_price"],
                        event["exit_price"],
                        event["pnl"],
                        "CLOSED"
                    )

                    is_zombie = "Zombie" in str(event.get("reason", ""))
                    header_icon = "🧟 *Zombie Trade Killer (Slot Freed!)*" if is_zombie else "🏁 *Real-Time Exit (Slot Freed!)*"

                    alert_msg = (
                        header_icon + "\n"
                        "• Exchange: `Bybit V5 Linear (Hybrid)` ⚡\n"
                        "• Pair: `" + symbol + "` (" + side_name + " " + str(self.engine.leverage) + "x)\n"
                        "• Reason: `" + str(event['reason']) + "`\n"
                        "• Entry Price: `$" + fmt_p(event['entry_price']) + "`\n"
                        "• Exit Price: `$" + fmt_p(event['exit_price']) + "`\n"
                        "• Net PnL: `$" + f"{event['pnl']:+.2f}" + "`\n"
                        "• Wallet Balance: `$" + f"{self.engine.cash_balance:.2f}" + "`\n"
                        "• Active Slots: `" + str(len(self.engine.positions)) + "/" + str(self.engine.max_concurrent) + "`"
                    )
                    await asyncio.to_thread(send_telegram_alert, alert_msg)

    async def bybit_scanner_and_trading_loop(self):
        while self.is_running:
            try:
                # 1. Bitcoin Market Regime Check
                regime_data = await asyncio.to_thread(strategy_agent.check_btc_market_regime)
                self.btc_regime = regime_data

                # 2. Fetch all Linear Tickers
                all_tickers = await asyncio.to_thread(bybit_client.fetch_all_linear_tickers)
                valid_candidates = []
                radar_items = []

                min_turnover = getattr(config, "MIN_24H_TURNOVER_USDT", 1000000.0)

                for item in all_tickers:
                    sym = item.get("symbol", "")
                    if not sym.endswith("USDT"):
                        continue

                    last_price = float(item.get("lastPrice", 0.0) or 0.0)
                    turnover_24h = float(item.get("turnover24h", 0.0) or 0.0)
                    change_24h_pct = float(item.get("price24hPcnt", 0.0) or 0.0) * 100.0

                    if last_price <= 0:
                        continue

                    await self.handle_fast_tick(sym, last_price)

                    radar_items.append({
                        "symbol": sym,
                        "price": last_price,
                        "change_pct": round(change_24h_pct, 2),
                        "turnover": turnover_24h
                    })

                    if turnover_24h >= min_turnover:
                        valid_candidates.append({
                            "symbol": sym,
                            "price": last_price,
                            "turnover": turnover_24h,
                            "change_pct": change_24h_pct,
                            "trend": "UP" if change_24h_pct >= 0 else "DOWN"
                        })

                if radar_items:
                    radar_items.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
                    self.market_radar = radar_items[:15]

                # Circuit Breaker Check
                if self.engine.is_circuit_breaker_triggered():
                    if not self.circuit_breaker_alerted:
                        self.trading_enabled = False
                        self.circuit_breaker_alerted = True
                        await asyncio.to_thread(
                            send_telegram_alert,
                            "🚨 *CIRCUIT BREAKER TRIGGERED!* Net loss reached 10%. Trading halted!"
                        )

                # 3. Stage 2: Deep Scan for Entry Signals
                free_slots = self.engine.max_concurrent - len(self.engine.positions)
                if self.trading_enabled and free_slots > 0 and valid_candidates:
                    valid_candidates.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
                    top_pool = valid_candidates[:25]

                    verified_picks = []
                    for cand in top_pool:
                        sym = cand["symbol"]
                        if sym in self.engine.positions:
                            continue

                        signal, atr_val, vol_ratio, macro_trend = await asyncio.to_thread(
                            strategy_agent.evaluate_market_with_atr,
                            sym,
                            cand["trend"],
                            cand["price"]
                        )

                        if signal == "LONG" and not self.btc_regime.get("allow_long", True):
                            continue

                        if signal in ["LONG", "SHORT"]:
                            vol_bonus = min(30.0, (vol_ratio - 1.0) * 20.0)
                            score = round((abs(cand["change_pct"]) * 3.0) + 60.0 + vol_bonus, 1)
                            verified_picks.append({
                                "symbol": sym,
                                "signal": signal,
                                "price": cand["price"],
                                "score": score,
                                "atr": atr_val,
                                "vol_ratio": vol_ratio,
                                "macro_trend": macro_trend
                            })

                    verified_picks.sort(key=lambda x: x["score"], reverse=True)

                    for pick in verified_picks:
                        if len(self.engine.positions) >= self.engine.max_concurrent:
                            break

                        sym = pick["symbol"]
                        sig = pick["signal"]
                        cur_p = pick["price"]
                        score = pick["score"]
                        atr = pick["atr"]
                        v_ratio = pick["vol_ratio"]
                        m_trend = pick["macro_trend"]

                        if not self.engine.can_open_position(sym, side=sig):
                            continue

                        # --- Fundamental Research Bot Guard (Cloud Supabase Bridge) ---
                        should_block, block_reason = bot_bridge.should_block_trade(sig)
                        if should_block:
                            print(f"[Fundamental Guard]: Blocked {sig} on {sym} -> {block_reason}")
                            continue

                        margin_amount = self.engine.calculate_position_size(score=score)
                        order_success = self.engine.execute_order(sym, sig, margin_amount, cur_p, custom_atr=atr, score=score)

                        if order_success:
                            pos = self.engine.positions.get(sym, {})
                            entry_p = pos.get("entry_price", cur_p)
                            partial_p = pos.get("partial_tp_price", entry_p)
                            tp_p = pos.get("tp_price", entry_p)
                            sl_p = pos.get("sl_price", entry_p)

                            await asyncio.to_thread(
                                database.record_trade,
                                sym,
                                sig + "_" + str(self.engine.leverage) + "X",
                                margin_amount,
                                entry_p,
                                None,
                                0.0,
                                "OPEN"
                            )

                            long_count = sum(1 for p in self.engine.positions.values() if p["side"] == "LONG")
                            short_count = sum(1 for p in self.engine.positions.values() if p["side"] == "SHORT")

                            conviction_badge = "🔥 High (2.5%)" if score >= 90 else ("⚡ Standard (2.0%)" if score >= 75 else "⚠️ Baseline (1.5%)")
                            side_emoji = "🟢" if sig == "LONG" else "🔴"
                            alert_msg = (
                                side_emoji + " *Bybit Hybrid 300+ Scanner: " + str(self.engine.leverage) + "x Order (" + sig + ")*\n"
                                "• Pair: `" + sym + "` (Score: `" + str(score) + "`)\n"
                                "• BTC Regime: `" + self.btc_regime.get("regime", "STABLE") + " 🛡️`\n"
                                "• Conviction: `" + conviction_badge + "`\n"
                                "• Allocated Margin: `$" + f"{margin_amount:.2f}" + "`\n"
                                "• Exposure: `" + str(long_count) + "L / " + str(short_count) + "S (Cap: 3)` ⚖️\n"
                                "• Macro Alignment: `" + m_trend + " + 15m " + sig + "` 🧭\n"
                                "• Volume Spike: `" + f"{v_ratio:.2f}x" + " Avg Vol` 🔥\n"
                                "• Entry Price: `$" + fmt_p(entry_p) + "`\n"
                                "• 50% Partial TP (1.5x ATR): `$" + fmt_p(partial_p) + "` 🎯\n"
                                "• Dynamic SL (1.5x ATR): `$" + fmt_p(sl_p) + "`\n"
                                "• Active Slots: `" + str(len(self.engine.positions)) + "/" + str(self.engine.max_concurrent) + "`\n"
                                "• Wallet Balance: `$" + f"{self.engine.cash_balance:.2f}" + "`"
                            )
                            await asyncio.to_thread(send_telegram_alert, alert_msg)

            except Exception as e:
                print("[Bybit Scanner Loop Error]:", e)

            await asyncio.sleep(3)

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
                            long_c = 0
                            short_c = 0
                            for sym, p in self.engine.positions.items():
                                entry_str = fmt_p(p["entry_price"])
                                tp_str = fmt_p(p["tp_price"])
                                sl_str = fmt_p(p["sl_price"])
                                side_str = p["side"]
                                if side_str == "LONG":
                                    long_c += 1
                                else:
                                    short_c += 1
                                be_tag = " [BE🛡️]" if p.get("partial_tp_done") else ""
                                margin_str = f"{p['margin']:.2f}"
                                line = "• " + sym + " (" + side_str + be_tag + "): Margin $" + margin_str + " | Ent $" + entry_str + " | SL $" + sl_str + " | TP $" + tp_str
                                active_desc.append(line)
                            pos_text = "\n".join(active_desc) if active_desc else "None (0/5 Active Slots)"

                            state_str = "ACTIVE" if self.trading_enabled else "PAUSED"
                            regime_icon = "🟢" if self.btc_regime.get("regime") == "STABLE" else "🚨"

                            # Read live macro bias from bridge
                            macro_info = bot_bridge.get_current_market_bias()
                            freeze_tag = " ⛔ (NEWS FREEZE)" if macro_info.get("is_news_freeze") else " ✅"

                            status_reply = (
                                "📊 *Chama Capital Management - Status:*\n"
                                "• Engine State: " + state_str + "\n"
                                "• Exchange Feed: `Bybit Hybrid (300+ Pairs)` ⚡\n"
                                "• Database: `" + ("Cloud PostgreSQL (Supabase)" if database.is_postgres else "Local SQLite") + "` 🗄️\n"
                                "• Fundamental Bias: `" + str(macro_info.get("bias_label")) + " (" + f"{macro_info.get('composite_score', 0):+.1f}" + ")`" + freeze_tag + "\n"
                                "• BTC Regime: " + regime_icon + " `" + self.btc_regime.get("regime", "STABLE") + "`\n"
                                "• Directional Exposure: `" + str(long_c) + " LONG / " + str(short_c) + " SHORT (Max 3/side)` ⚖️\n"
                                "• Tracked Pairs: " + str(len(self.latest_prices)) + " Live Pairs\n"
                                "• Available Cash: $" + f"{self.engine.cash_balance:.2f}" + "\n"
                                "• Realized PnL: $" + f"{self.engine.realized_pnl:+.2f}" + "\n"
                                "• Active Slots: " + str(len(self.engine.positions)) + "/" + str(self.engine.max_concurrent) + "\n"
                                + pos_text
                            )
                            await asyncio.to_thread(send_telegram_alert, status_reply)

                        elif text == "/stop":
                            self.trading_enabled = False
                            await asyncio.to_thread(send_telegram_alert, "🛑 *Trading Paused!* Exits & Break-Even active.")

                        elif text == "/start":
                            self.trading_enabled = True
                            self.circuit_breaker_alerted = False
                            await asyncio.to_thread(send_telegram_alert, "▶️ *Trading Resumed!* Scanner active.")

                        elif text == "/closeall":
                            closed_count = 0
                            for sym in list(self.engine.positions.keys()):
                                cur_p = self.latest_prices.get(sym, self.engine.positions[sym]["entry_price"])
                                closed = self.engine._close_token_position(sym, "Manual /closeall", cur_p)
                                if closed:
                                    closed_count += 1
                            await asyncio.to_thread(send_telegram_alert, f"⚠️ *Manual Exit Triggered!* Closed {closed_count} position(s).")

            except Exception as e:
                print("[Telegram Listener Error]:", e)

            await asyncio.sleep(2)

    async def run_parallel_trading(self):
        db_type = "Cloud PostgreSQL (Supabase)" if database.is_postgres else "Local SQLite"
        await asyncio.to_thread(
            send_telegram_alert,
            f"🚀 *Bybit V5 Quant Engine Online (Fundamental Guard Synced)!* ⚡\n"
            f"• Market Feed: `Zero-Drop Multi-Stream Feed` 🌐\n"
            f"• Fundamental Research Bridge: `Cloud PostgreSQL (Supabase)` 🧠\n"
            f"• Scanner: `300+ Pairs 2-Stage Filter ($1M+ Vol)`\n"
            f"• Persistence: `{db_type}` 🗄️\n"
            f"• BTC Crash Guard & Zombie Killer: Fully Armed 🛡️🧟"
        )
        await asyncio.gather(
            self.bybit_scanner_and_trading_loop(),
            self.telegram_command_listener()
        )


if __name__ == "__main__":
    bot = MultiTokenBot()
    try:
        asyncio.run(bot.run_parallel_trading())
    except KeyboardInterrupt:
        print("Bot stopped.")
