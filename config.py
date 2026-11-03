# ==========================================
# 10X ISOLATED FUTURES BOT CONFIGURATION
# ==========================================

STARTING_CAPITAL = 1000.0
LEVERAGE = 10                         # 10x Isolated Leverage Multiplier
POSITION_MARGIN_PERCENT = 0.02        # 2% Margin per trade ($20 margin -> $200 exposure)
MAX_CONCURRENT_TRADES = 5             # Max 5 parallel slots

DAILY_LOSS_LIMIT_PERCENT = 0.10       # 10% daily drawdown circuit breaker
MAX_DAILY_DRAWDOWN_PERCENT = 0.10
MIN_LIQUIDITY_USD = 20000.0

# 10x Calibrated Targets (1:2 Risk-to-Reward)
TAKE_PROFIT_PERCENT = 0.020           # +2.0% Price move to TP (+20% ROE)
STOP_LOSS_PERCENT = 0.010             # -1.0% Price move to SL (-10% Loss)
TRAILING_STOP_PERCENT = 0.008         # 0.8% Trailing distance from peak
MAINTENANCE_MARGIN_PERCENT = 0.015    # 1.5% Exchange maintenance buffer
FUTURES_TAKER_FEE = 0.0005            # 0.05% fee applied on total notional size
