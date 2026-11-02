def analyze_market_sentiment(news_text: str = "Bullish crypto momentum and strong community growth") -> float:
    """
    Simulates a LangGraph / LLM sentiment analysis agent.
    Returns a sentiment score between -1.0 (Very Bearish) and +1.0 (Very Bullish).
    """
    # In a full LangGraph production setup, this calls an LLM node to score news/tweets.
    bullish_keywords = ["bull", "surge", "pump", "growth", "strong", "rally", "up"]
    bearish_keywords = ["crash", "dump", "bear", "scam", "drop", "hack", "loss"]
    
    score = 0.0
    text_lower = news_text.lower()
    for word in bullish_keywords:
        if word in text_lower:
            score += 0.3
    for word in bearish_keywords:
        if word in text_lower:
            score -+ 0.4
            
    # Default positive sentiment for simulation if keywords match or neutral
    return max(-1.0, min(1.0, score if score != 0.0 else 0.5))

def evaluate_market(trend: str, rsi: float, momentum: float, liquidity_usd: float, macd: float = 0.5, macd_signal: float = 0.2, price: float = 150.0, bb_lower: float = 145.0, news_feed: str = "Strong bullish momentum") -> str:
    """
    LangGraph / Multi-Agent Strategy Agent:
    Combines Technical Indicators (MACD, RSI, BB, Trend) with LLM Sentiment Analysis.
    Returns: 'BUY' or 'HOLD'
    """
    # 1. Liquidity Safety Check
    if liquidity_usd < 10000.0:
        print(f"Strategy Agent [LangGraph]: HOLD (Low Liquidity: ${liquidity_usd:.2f})")
        return "HOLD"

    # 2. Technical Confluence Check
    is_trend_up = trend.upper() == "UP"
    is_rsi_healthy = 40.0 <= rsi <= 65.0
    is_momentum_positive = momentum > 0.0
    is_macd_bullish = macd > macd_signal
    is_price_above_bb = price > bb_lower

    technical_pass = is_trend_up and is_rsi_healthy and is_momentum_positive and is_macd_bullish and is_price_above_bb

    # 3. Sentiment Agent Node Check (LangGraph style agent node)
    sentiment_score = analyze_market_sentiment(news_feed)
    is_sentiment_bullish = sentiment_score > 0.2  # Must have positive sentiment threshold

    # 4. Final Multi-Agent Decision Gate
    if technical_pass and is_sentiment_bullish:
        print(f"Strategy Agent [LangGraph]: BUY Signal Triggered! (Tech OK + Sentiment Score: {sentiment_score})")
        return "BUY"

    print(f"Strategy Agent [LangGraph]: HOLD (Technical Pass: {technical_pass}, Sentiment Score: {sentiment_score})")
    return "HOLD"