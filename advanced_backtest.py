import risk_manager
import strategy_agent
from paper_engine import PaperTradingEngine
from config import STARTING_CAPITAL

# Expanded historical dataset simulating multiple market cycles (Bull, Bear, Volatile)
EXTENDED_HISTORICAL_DATA = [
    {"step": 1, "price": 140.0, "trend": "UP", "rsi": 50, "momentum": 1.0, "liquidity": 40000.0, "honeypot": False, "macd": 0.5, "macd_sig": 0.2, "bb_lower": 135.0, "news": "Market stable"},
    {"step": 2, "price": 145.0, "trend": "UP", "rsi": 58, "momentum": 1.4, "liquidity": 45000.0, "honeypot": False, "macd": 0.8, "macd_sig": 0.3, "bb_lower": 139.0, "news": "Bullish momentum incoming"},
    {"step": 3, "price": 152.0, "trend": "UP", "rsi": 65, "momentum": 1.8, "liquidity": 50000.0, "honeypot": False, "macd": 1.2, "macd_sig": 0.5, "bb_lower": 144.0, "news": "Strong rally surge"},
    {"step": 4, "price": 148.0, "trend": "DOWN", "rsi": 45, "momentum": -0.8, "liquidity": 48000.0, "honeypot": False, "macd": -0.2, "macd_sig": 0.1, "bb_lower": 142.0, "news": "Correction phase"},
    {"step": 5, "price": 142.0, "trend": "DOWN", "rsi": 38, "momentum": -1.2, "liquidity": 42000.0, "honeypot": False, "macd": -0.6, "macd_sig": -0.2, "bb_lower": 138.0, "news": "Bearish dip"},
    {"step": 6, "price": 146.0, "trend": "UP", "rsi": 52, "momentum": 1.1, "liquidity": 46000.0, "honeypot": False, "macd": 0.4, "macd_sig": 0.1, "bb_lower": 140.0, "news": "Recovery wave"},
    {"step": 7, "price": 155.0, "trend": "UP", "rsi": 70, "momentum": 2.2, "liquidity": 55000.0, "honeypot": False, "macd": 1.5, "macd_sig": 0.8, "bb_lower": 148.0, "news": "Major breakout pump"},
]

def run_advanced_backtest():
    print("==================================================")
    print(" 📊 RUNNING ADVANCED HISTORICAL BACKTEST 📊")
    print("==================================================\n")

    engine = PaperTradingEngine(initial_capital=STARTING_CAPITAL)
    trades_taken = 0
    wins = 0
    losses = 0

    for candle in EXTENDED_HISTORICAL_DATA:
        step = candle["step"]
        price = candle["price"]
        
        print(f"--- [Market Tick #{step}] Price: ${price:.2f} | Wallet: ${engine.cash_balance:.2f} ---")
        
        # Check daily loss limit circuit breaker
        if risk_manager.check_daily_loss_limit(engine.realized_pnl):
            print("🚨 Circuit breaker triggered! Stopping backtest for the day.")
            break

        if engine.active_position:
            closed = engine.check_exit_conditions(price)
            if closed:
                trades_taken += 1
                if closed["pnl"] > 0:
                    wins += 1
                else:
                    losses += 1
                print(f"--> Position Closed: {closed['reason']} | Trade PnL: ${closed['pnl']:+.2f}\n")
            continue

        signal = strategy_agent.evaluate_market(
            trend=candle["trend"], rsi=candle["rsi"], momentum=candle["momentum"], 
            liquidity_usd=candle["liquidity"], macd=candle["macd"], macd_signal=candle["macd_sig"], 
            price=price, bb_lower=candle["bb_lower"], news_feed=candle["news"]
        )
        
        if signal == "BUY":
            trade_amt = engine.calculate_position_size() # 2% of capital ($1.00 out of $50)
            if risk_manager.validate_pre_trade_safety(
                trade_amount=trade_amt, estimated_slippage=0.005,
                liquidity_usd=candle["liquidity"], is_honeypot=candle["honeypot"]
            ):
                engine.execute_order("SOL/USDC", "BUY", trade_amt, price)
        print("")

    win_rate = (wins / trades_taken * 100) if trades_taken > 0 else 0
    print("==================================================")
    print(f" 📈 Advanced Backtest Summary Results:")
    print(f" Total Trades Executed : {trades_taken}")
    print(f" Wins / Losses         : {wins}W / {losses}L ({win_rate:.1f}% Win Rate)")
    print(f" Final Wallet Balance  : ${engine.cash_balance:.2f}")
    print(f" Total Realized PnL    : ${engine.realized_pnl:+.2f}")
    print("==================================================")

if __name__ == "__main__":
    run_advanced_backtest()