# ==========================================
# 100X ULTRA-SCALP FUTURES CONFIGURATION
# ==========================================

# Capital & Leverage Rules
STARTING_CAPITAL = 1000.0  #[cite: 12]
LEVERAGE = 100                        # 100x Isolated Leverage
POSITION_MARGIN_PERCENT = 0.02        # 2% of real-time balance as margin ($20 -> $2,000 exposure)
MAX_CONCURRENT_TRADES = 3             # Max 3 parallel slots

# Risk & Circuit Breakers
DAILY_LOSS_LIMIT_PERCENT = 0.10       # 10% daily drawdown circuit breaker
MAX_DAILY_DRAWDOWN_PERCENT = 0.10     # Alias for compatibility
MIN_LIQUIDITY_USD = 20000.0           # Minimum liquidity filter

# 100x Calibrated Micro-Targets
# 0.8% price move = +80% ROE | 0.4% price move = -40% loss
TAKE_PROFIT_PERCENT = 0.008           # +0.8% Price move to TP (+80% ROE)
STOP_LOSS_PERCENT = 0.004             # -0.4% Price move to SL (-40% Loss, before liquidation)
TRAILING_STOP_PERCENT = 0.003         # 0.3% Trailing distance from peak
MAINTENANCE_MARGIN_PERCENT = 0.004    # 0.4% Exchange maintenance buffer
FUTURES_TAKER_FEE = 0.0005            # 0.05% fee applied on total $2,000 notional size
