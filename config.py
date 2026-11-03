# ==========================================
# 25X SCALP FUTURES CONFIGURATION
# ==========================================

# Capital & Leverage Multiplier
STARTING_CAPITAL = 1000.0
LEVERAGE = 25                         # 25x Isolated Leverage
POSITION_MARGIN_PERCENT = 0.02        # 2% of real-time balance as margin ($20 -> $500 exposure)
MAX_CONCURRENT_TRADES = 3             # Max 3 parallel slots

# Risk Limits & Circuit Breaker
DAILY_LOSS_LIMIT_PERCENT = 0.10       # 10% daily drawdown circuit breaker
MAX_DAILY_DRAWDOWN_PERCENT = 0.10
MIN_LIQUIDITY_USD = 20000.0

# 25x Calibrated Targets (Tight Scalp)
# 1.2% price move = +30% ROE | 0.8% price move = -20% Loss
TAKE_PROFIT_PERCENT = 0.012           # +1.2% Price move to TP (+30% ROE)
STOP_LOSS_PERCENT = 0.008             # -0.8% Price move to SL (-20% Loss, safe before -3% Liq)
TRAILING_STOP_PERCENT = 0.006         # 0.6% Trailing distance from peak
MAINTENANCE_MARGIN_PERCENT = 0.010    # 1.0% Exchange maintenance margin buffer
FUTURES_TAKER_FEE = 0.0005            # 0.05% fee on $500 notional size
