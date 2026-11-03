import requests
import numpy as np

def fetch_klines(binance_symbol: str, interval="15m", limit=50):
    """
    Fetch real OHLCV klines from Binance Vision API (US-friendly, no geo-block).
    Returns a list of closing prices or None.
    """
    urls = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={binance_symbol}&interval={interval}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={binance_symbol}&interval={interval}&limit={limit}"
    ]
    for url in urls:
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    # Close prices are at index 4 in kline response arrays
                    closes = [float(candle[4]) for candle in data]
                    return closes
        except Exception:
            continue
    return None


def calculate_wilders_rsi(closes, period=14):
    """Calculate standard Wilder's RSI from a list of closing prices."""
    if len(closes) < period + 1:
        return 50.0  # Default neutral if not enough data
    
    deltas = np.diff(closes)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    
    if down == 0:
        return 100.0
    
    rs = up / down
    rsi = 100.0 - (100.0 / (1.0 + rs))
    
    # Wilder's smoothing for subsequent values
    for delta in deltas[period:]:
        upval = delta if delta > 0 else 0.0
        downval = -delta if delta < 0 else 0.0
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        if down == 0:
            rsi = 100.0
        else:
            rs = up / down
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
    return float(rsi)


def calculate_ema(closes, period=20):
    """Calculate Exponential Moving Average (EMA)."""
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    a = np.convolve(closes, weights, mode='valid')
    return float(a[-1])


def evaluate_market(trend: str, rsi: float, momentum: float, liquidity_usd: float, macd: float, macd_signal: float, price: float, binance_symbol: str = None) -> str:
    """
    Enhanced Market Evaluation Engine utilizing real Klines, Wilder's RSI, and EMA validation.
    """
    # 1. Liquidity Safety Filter
    if liquidity_usd < 20000.0:
        return "HOLD"

    # 2. Fetch Real 15m Klines if symbol is provided
    if binance_symbol:
        closes = fetch_klines(binance_symbol, interval="15m", limit=50)
        if closes and len(closes) >= 20:
            rsi = calculate_wilders_rsi(closes, period=14)
            ema20 = calculate_ema(closes, period=20)
            ema50 = calculate_ema(closes, period=50)
            
            # Trend confirmation via EMA Crossover & Wilder's RSI
            if price > ema20 and ema20 > ema50 and rsi < 68.0:
                return "LONG"
            elif price < ema20 and ema20 < ema50 and rsi > 32.0:
                return "SHORT"
            return "HOLD"

    # 3. Fallback heuristic evaluation if symbol klines unavailable
    if trend == "UP" and rsi < 65.0 and momentum > 0.6:
        return "LONG"
    elif trend == "DOWN" and rsi > 35.0 and momentum < 0.4:
        return "SHORT"
        
    return "HOLD"
