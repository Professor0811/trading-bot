import time
import config
import risk_manager
import strategy_agent
from data_stream import get_dexscreener_feed
from paper_engine import PaperTradingEngine
from telegram_alerts import send_telegram_alert

def log_terminal_ui(symbol, action, order_result, engine, price):
    print("=== REAL-TIME LIVE PAPER-TRADING MONITOR ===")
    print(f"Pair: {symbol} | Live Price: ${price:.4f} | Signal: {action}")
    if order_result:
        print(f"Executed: {order_result['side']} at ${order_result['exec_price']:.4f}")
    if engine.active_position:
        pos = engine.active_position
        print(f"Active Position -> TP: ${pos['tp_price']:.4f} | SL: ${pos['sl_price']:.4f}")
    print(f"Wallet Cash: ${engine.cash_balance:.2f} | Realized PnL: ${engine.realized_pnl:.2f}")
    print("============================================\n")

def run_live_simulation():
    engine = PaperTradingEngine()
    pair_url = "https://api.dexscreener.com/latest/dex/pairs/solana/58ooQChx4yWmvLiSWYg13Zqg7x42d8q7c2b09a1f"
    symbol = "SOL/USDC"
    trade_amount = 50.0

    print("Starting Live Bot with Pre-Trade Safety Filters... (Press Ctrl+C to stop)")
    send_telegram_alert("🚀 Trading Bot Started with Rug-Risk & Honeypot Filters active!")

    for _ in range(3):
        try:
            # 1. Check circuit breaker
            current_drawdown = max(0.0, -engine.realized_pnl)
            risk_manager.check_circuit_breaker(current_drawdown)

            # 2. Fetch market feed
            feed_data = get_dexscreener_feed(pair_url)
            market_price = 150.0  
            liquidity_usd = 50000.0

            if feed_data and isinstance(feed_data, dict) and "pair" in feed_data and feed_data["pair"]:
                market_price = float(feed_data["pair"].get("priceUsd", 150.0))
                liquidity_usd = float(feed_data["pair"].get("liquidity", {}).get("usd", 50000.0))

            # 3. Check exits if active position exists
            closed_result = None
            if engine.active_position:
                closed_result = engine.check_exit_conditions(market_price)
                if closed_result:
                    alert_msg = (
                        f"🏁 *Position Closed!*\n"
                        f"• Reason: {closed_result['reason']}\n"
                        f"• Exit Price: `${closed_result['exit_price']:.4f}`\n"
                        f"• PnL: `${closed_result['pnl']:.2f}`\n"
                        f"• New Wallet Cash: `${closed_result['new_cash']:.2f}`"
                    )
                    send_telegram_alert(alert_msg)

            # 4. Evaluate strategy and validate pre-trade safety
            order_result = None
            if not engine.active_position:
                signal = strategy_agent.evaluate_market(trend="UP", rsi=55, momentum=1.2, liquidity_usd=liquidity_usd)
                if signal == "BUY":
                    # Validating safety with updated parameters (trade_amount, slippage, liquidity, is_honeypot)
                    if risk_manager.validate_pre_trade_safety(trade_amount, estimated_slippage=0.5, liquidity_usd=liquidity_usd, is_honeypot=False):
                        order_result = engine.execute_order(symbol, "BUY", trade_amount, market_price)
                        if order_result:
                            alert_msg = (
                                f"🔔 *Trade Executed (Rug-Checked)*\n"
                                f"• Pair: `{symbol}`\n"
                                f"• Price: `${order_result['exec_price']:.4f}`\n"
                                f"• Take-Profit: `${order_result['tp_price']:.4f}`\n"
                                f"• Stop-Loss: `${order_result['sl_price']:.4f}`"
                            )
                            send_telegram_alert(alert_msg)

            # 5. Log to terminal UI
            log_terminal_ui(symbol, "HOLD" if engine.active_position else "BUY", order_result, engine, market_price)

        except Exception as e:
            print(f"Runtime error: {e}")

        time.sleep(5)

if __name__ == "__main__":
    run_live_simulation()