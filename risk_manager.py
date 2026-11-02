import sys
from config import DAILY_LOSS_LIMIT_PERCENT, STARTING_CAPITAL, MIN_LIQUIDITY_USD

def check_daily_loss_limit(total_realized_pnl: float) -> bool:
    """
    Checks if the daily net loss has hit 10% of starting capital ($5.00 out of $50).
    If hit, triggers the daily circuit breaker to pause/stop the bot for the day.
    """
    max_allowed_loss = STARTING_CAPITAL * DAILY_LOSS_LIMIT_PERCENT
    
    # If realized PnL is negative and exceeds 10% loss
    if total_realized_pnl <= -max_allowed_loss:
        print(f"\n🚨 [DAILY CIRCUIT BREAKER TRIGGERED] 🚨")
        print(f"Daily Net Loss (${abs(total_realized_pnl):.2f}) has reached or exceeded the 10% limit (${max_allowed_loss:.2f}).")
        print(f"Bot execution paused for the day to protect capital. Resuming next trading day.")
        return True
    return False

def validate_pre_trade_safety(trade_amount: float, estimated_slippage: float, liquidity_usd: float, is_honeypot: bool) -> bool:
    """
    Pre-trade safety validation: Checks for honeypots, low liquidity, and excessive slippage.
    """
    if is_honeypot:
        print("Risk Manager [REJECTED]: Token identified as a potential Honeypot scam!")
        return False
        
    if liquidity_usd < MIN_LIQUIDITY_USD:
        print(f"Risk Manager [REJECTED]: Insufficient liquidity (${liquidity_usd:.2f} < ${MIN_LIQUIDITY_USD})")
        return False

    if estimated_slippage > 0.015:
        print(f"Risk Manager [REJECTED]: Slippage too high ({estimated_slippage * 100}%)")
        return False

    print("Risk Manager [PASSED]: Pre-trade safety validation successful.")
    return True