# ==========================================
# 5X FUTURES TRADING BOT CONFIGURATION
# ==========================================

# Capital & Leverage Rules
STARTING_CAPITAL = 1000.0
LEVERAGE = 5                          # 5x Isolated Leverage
POSITION_MARGIN_PERCENT = 0.02        # 2% of real-time balance allocated as isolated margin
MAX_CONCURRENT_TRADES = 3             # Max 3 open positions simultaneously

# Risk & Circuit Breakers
DAILY_LOSS_LIMIT_PERCENT = 0.10       # 10% daily drawdown circuit breaker
MAX_DAILY_DRAWDOWN_PERCENT = 0.10     # Alias for compatibility
MIN_LIQUIDITY_USD = 20000.0           # Minimum liquidity filter

# 5x Futures Take-Profit & Stop-Loss (Calibrated for 5x)
# Under 5x: 3% price move = +15% ROE | 1.2% price move = -6% loss
TAKE_PROFIT_PERCENT = 0.03            # +3.0% Price move to TP
STOP_LOSS_PERCENT = 0.012             # -1.2% Price move to SL
TRAILING_STOP_PERCENT = 0.010         # 1.0% Trailing distance from peak
MAINTENANCE_MARGIN_PERCENT = 0.015    # 1.5% exchange maintenance threshold
FUTURES_TAKER_FEE = 0.0005            # 0.05% fee applied on total leveraged position size
