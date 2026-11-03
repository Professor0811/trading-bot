# ==========================================
# TRADING BOT GLOBAL CONFIGURATION
# ==========================================

# Capital & Risk Allocations
STARTING_CAPITAL = 1000.0
POSITION_SIZE_PERCENT = 0.02          # 2% of real-time balance per trade
MAX_CONCURRENT_TRADES = 3             # Max 3 parallel slots

# Drawdown Limits & Circuit Breaker
DAILY_LOSS_LIMIT_PERCENT = 0.10       # 10% daily drawdown limit (Fixes ImportError)
MAX_DAILY_DRAWDOWN_PERCENT = 0.10     # Alias for backward compatibility
DAILY_DRAWDOWN_FLOOR_USD = 20.0       # Fallback fixed floor

# Market Execution & Liquidity
MIN_LIQUIDITY_USD = 20000.0           # Filter pairs below $20k liquidity
MAX_SLIPPAGE_PERCENT = 0.015          # 1.5% max allowed slippage
SIMULATED_SLIPPAGE = 0.005            # 0.5% realistic simulated execution drag

# Strategy Targets (1:2.4 Risk-to-Reward)
TAKE_PROFIT_PERCENT = 0.06            # +6.0% Take Profit
STOP_LOSS_PERCENT = 0.025             # -2.5% Stop Loss
TRAILING_STOP_PERCENT = 0.020         # 2.0% Trailing SL from peak
