import risk_manager
import strategy_agent
from paper_engine import PaperTradingEngine
from config import STARTING_CAPITAL

# Test candles with MACD, Bollinger Bands, and Sentiment
HISTORICAL_DATA = [
    {"step": 1, "price": 150.00, "trend": "UP", "rsi": 55, "momentum": 1.2, "liquidity": 50000.0, "honeypot": False, "macd": 0.8, "macd_sig": 0.3, "bb_lower": 142.0, "news": "Strong bullish momentum"}, 
    {"step": 2, "price": 153.50, "trend": "UP", "rsi": 60, "momentum": 1.5, "liquidity": 52000.0, "honeypot": False, "macd": 0.9, "macd_sig": 0.4, "bb_lower": 145.0, "news": "Bullish rally surge"}, 
    {"step": 3, "price": 159.00, "trend": "UP", "rsi": 68, "momentum": 2.0, "liquidity": 55000.0, "honeypot": False, "macd": 1.1, "macd_sig": 0.5, "bb_lower": 150.0, "news": "Growth pump"}, 
    {"step": 4, "price": 160.00, "trend": "UP", "rsi": 58, "momentum": 1.1, "liquidity": 5000.0,  "honeypot": False, "macd": 0.5, "macd_sig": 0.2, "bb_lower": 152.0, "news": "Bullish"}, 
    {"step": 5, "price": 162.00, "trend": "UP", "rsi": 52, "momentum": 0.9, "liquidity": 45000.0, "honeypot": True,  "macd": 0.4, "macd_sig": 0.2, "bb_lower": 155.0, "news": "Bullish"}, 
]

def run_verification():
    print("==================================================")
    print(" 🔍 RUNNING SYSTEM VERIFICATION & BACKTEST 🔍")
    print("==================================================\n")

    engine = PaperTradingEngine(initial_capital=STARTING_CAPITAL)
    
    for candle in HISTORICAL_DATA:
        step = candle["step"]
        price = candle["price"]
        
        print(f"--- [Tick #{step}] Price: ${price:.2f} | Wallet: ${engine.cash_balance:.2f} ---")
        
        # Check daily loss limit (10% max loss circuit breaker)
        if risk_manager.check_daily_loss_limit(engine.realized_pnl):
            print("Bot stopped for the day due to daily loss limit!")
            break

        if engine.active_position:
            closed = engine.check_exit_conditions(price)
            if closed:
                print(f"--> Closed Position: {closed['reason']} | PnL: ${closed['pnl']:+.2f}\n")
            continue

        signal = strategy_agent.evaluate_market(
            trend=candle["trend"], rsi=candle["rsi"], momentum=candle["momentum"], 
            liquidity_usd=candle["liquidity"], macd=candle["macd"], macd_signal=candle["macd_sig"], 
            price=price, bb_lower=candle["bb_lower"], news_feed=candle["news"]
        )
        
        if signal == "BUY":
            trade_amt = engine.calculate_position_size() # Should be 2% ($1.00)
            if risk_manager.validate_pre_trade_safety(
                trade_amount=trade_amt, estimated_slippage=0.005,
                liquidity_usd=candle["liquidity"], is_honeypot=candle["honeypot"]
            ):
                engine.execute_order("SOL/USDC", "BUY", trade_amt, price)
        print("")

    print("==================================================")
    print(f" Final Verification Results:")
    print(f" Cash Balance : ${engine.cash_balance:.2f}")
    print(f" Realized PnL : ${engine.realized_pnl:+.2f}")
    print("==================================================")

if __name__ == "__main__":
    run_verification()