import os

# Bybit API Credentials from Render Environment
BYBIT_API_KEY = os.environ.get("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "")
BYBIT_TESTNET = os.environ.get("BYBIT_TESTNET", "False").lower() in ["true", "1"]
BYBIT_DEMO_MODE = os.environ.get("BYBIT_DEMO_MODE", "True").lower() in ["true", "1"]

# Capital & Leverage Rules
STARTING_CAPITAL = 1000.0
LEVERAGE = 10
POSITION_MARGIN_PERCENT = 0.02
MAX_CONCURRENT_TRADES = 5
MAX_SAME_SIDE_TRADES = 3

# Risk Management & ATR Stops
DAILY_LOSS_LIMIT_PERCENT = 0.10
STOP_LOSS_PERCENT = 0.02
TAKE_PROFIT_PERCENT = 0.04
TRAILING_STOP_PERCENT = 0.008
FUTURES_TAKER_FEE = 0.00055
MAINTENANCE_MARGIN_PERCENT = 0.005

# Scanner & Liquidity Rules (Both names supported for backward compatibility)
MIN_LIQUIDITY_USD = 5000000.0
MIN_24H_TURNOVER_USDT = 5000000.0
