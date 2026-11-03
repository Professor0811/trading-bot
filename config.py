# ==========================================
# 200X ULTRA-EXPERIMENTAL CONFIGURATION
# ==========================================

STARTING_CAPITAL = 1000.0  #[cite: 12]
LEVERAGE = 200                        # 200x Isolated Leverage Multiplier
POSITION_MARGIN_PERCENT = 0.01        # Margin එක 1% ($10 -> $2,000 exposure)
MAX_CONCURRENT_TRADES = 3

# 200x Targets: Micro-fractional price moves
# 0.4% price move = +80% ROE | 0.2% price move = -40% loss
TAKE_PROFIT_PERCENT = 0.004           # +0.4% Price move to TP (+80% ROE)
STOP_LOSS_PERCENT = 0.002             # -0.2% Price move to SL (-40% Loss, before 0.3% liquidation)
TRAILING_STOP_PERCENT = 0.0015        # 0.15% Trailing distance
MAINTENANCE_MARGIN_PERCENT = 0.002    # 0.2% Maintenance margin buffer
FUTURES_TAKER_FEE = 0.0005            # 0.05% taker fee on notional size
