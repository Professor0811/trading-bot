import asyncio
import random
from datetime import datetime
import risk_manager
import strategy_agent
from paper_engine import PaperTradingEngine
from config import STARTING_CAPITAL
from trade_logger import log_trade

# List of target tokens to trade in parallel
WATCH_LIST = ["SOL/USDC", "BONK/USDC", "JUP/USDC"]

class MultiTokenBot:
    def __init__(self):
        self.engine = PaperTradingEngine(initial_capital=STARTING_CAPITAL)
        self.is_running = True

    async def monitor_token(self, symbol: str):
        print(f"[{symbol}] Starting asynchronous market monitor...")
        
        while self.is_running:
            # Check daily loss limit circuit breaker
            if risk_manager.check_daily_loss_limit(self.engine.realized_pnl):
                print("🚨 Daily Loss Limit hit across bot. Stopping all token monitors.")
                self.is_running = False
                break

            # Simulated live market data fetch for the specific token
            current_price = 150.0 + random.uniform(-5.0, 5.0)
            rsi = random.randint(40, 70)
            momentum = random.uniform(0.5, 2.0)
            liquidity = random.uniform(20000.0, 100000.0)
            honeypot = False
            macd = random.uniform(0.1, 1.5)
            macd_sig = random.uniform(0.1, 0.8)
            bb_lower = current_price * 0.95

            print(f"[{symbol}] Price: ${current_price:.2f} | RSI: {rsi} | Wallet: ${self.engine.cash_balance:.2f}")

            # Check existing position exits
            if self.engine.active_position and self.engine.active_position["symbol"] == symbol:
                closed = self.engine.check_exit_conditions(current_price)
                if closed:
                    print(f"[{symbol}] Closed Position: {closed['reason']} | PnL: ${closed['pnl']:+.2f}\n")
            
            # Evaluate entry signal if no active position
            elif not self.engine.active_position:
                signal = strategy_agent.evaluate_market(
                    trend="UP", rsi=rsi, momentum=momentum, 
                    liquidity_usd=liquidity, macd=macd, macd_signal=macd_sig, 
                    price=current_price, bb_lower=bb_lower, news_feed="Parallel market surge"
                )
                
                if signal == "BUY":
                    trade_amt = self.engine.calculate_position_size() # 2% of capital ($1.00)
                    if risk_manager.validate_pre_trade_safety(
                        trade_amount=trade_amt, estimated_slippage=0.005,
                        liquidity_usd=liquidity, is_honeypot=honeypot
                    ):
                        self.engine.execute_order(symbol, "BUY", trade_amt, current_price)

            # Asynchronous delay between ticks for this token
            await asyncio.sleep(3)

    async def run_parallel_trading(self):
        print("==================================================")
        print(" 🚀 STARTING MULTI-TOKEN PARALLEL TRADING BOT 🚀 ")
        print("==================================================")
        print(f"Watching Pairs: {WATCH_LIST}")
        print(f"Starting Capital: ${STARTING_CAPITAL} | 2% Position Sizing Active\n")

        # Run monitors for all tokens concurrently using asyncio.gather
        tasks = [self.monitor_token(symbol) for symbol in WATCH_LIST]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    bot = MultiTokenBot()
    try:
        asyncio.run(bot.run_parallel_trading())
    except KeyboardInterrupt:
        print("\nBot stopped manually by user.")