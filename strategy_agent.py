"""
Strategy Agent: Generates LONG and SHORT trade signals based on 
trend confluence, RSI pullback exhaustion, and momentum indicators.
"""

def evaluate_market(
    trend: str,
    rsi: float,
    momentum: float,
    liquidity_usd: float,
    macd: float = 0.0,
    macd_signal: float = 0.0,
    price: float = 0.0
) -> str:
    """
    Evaluates market conditions for 5x Futures entries:
    - Returns 'LONG' for oversold pullbacks in an overall Uptrend.
    - Returns 'SHORT' for overbought rallies in an overall Downtrend.
    - Returns 'HOLD' when momentum is weak or liquidity is dangerous.
    """
    # 1. Safety Liquidity Filter (Avoid low-cap pump & dumps)
    if liquidity_usd < 20000.0:
        return "HOLD"

    # 2. LONG Signal: Uptrend + RSI Bullish Pullback Zone (38 - 56) + Positive Momentum
    if trend == "UP":
        if 38.0 <= rsi <= 56.0 and momentum >= 0.7:
            return "LONG"

    # 3. SHORT Signal: Downtrend + RSI Overbought Exhaustion (58 - 74) + Negative Momentum
    elif trend == "DOWN":
        if 58.0 <= rsi <= 74.0 and momentum <= 0.5:
            return "SHORT"

    return "HOLD"
