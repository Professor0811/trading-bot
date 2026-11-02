def verify_liquidity(liquidity_usd: float, min_liquidity: float = 20000.0) -> bool:
    """Filter out illiquid low-cap pairs prone to high slippage or manipulation."""
    return liquidity_usd >= min_liquidity


def evaluate_market(
    trend: str,
    rsi: float,
    momentum: float,
    liquidity_usd: float,
    macd: float = 0.5,
    macd_signal: float = 0.2,
    price: float = 150.0,
    bb_lower: float = 145.0,
    news_feed: str = "Neutral"
) -> str:
    """
    Optimized confluence engine targeting 60%+ win rate:
    - Filters liquidity to avoid illiquid traps.
    - Requires confirmed uptrend (UP).
    - Requires optimal RSI pullback zone (RSI between 38 and 58).
    - Requires positive momentum and MACD bullish cross.
    """
    # 1. Safety Liquidity Check
    if not verify_liquidity(liquidity_usd):
        return "HOLD"

    # 2. Strong BUY Confluence
    is_trend_bullish = (trend == "UP")
    is_rsi_sweet_spot = (38.0 <= rsi <= 58.0)
    is_momentum_positive = (momentum > 0.8)
    is_macd_bullish = (macd > macd_signal)

    if is_trend_bullish and is_rsi_sweet_spot and is_momentum_positive and is_macd_bullish:
        return "BUY"

    # 3. Defensive Exit / Sell Trigger
    if trend == "DOWN" or rsi >= 75.0:
        return "SELL"

    return "HOLD"
