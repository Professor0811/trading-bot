import time
import requests
import numpy as np

# In-memory cache to prevent API rate-limiting and event loop blocking
_KLINE_CACHE = {}
CACHE_TTL = 60  # Cache 15m klines for 60 seconds per symbol


def fetch_klines(binance_symbol: str, interval="15m", limit=55):
    """
    Fetch real OHLCV klines from Binance Vision API (US-friendly, no geo-block)
    with a 60-second smart cache.
    """
    now = time.time()
    if binance_symbol in _KLINE_CACHE:
        cached_time, cached_closes = _KLINE_CACHE[binance_symbol]
        if now - cached_time < CACHE_TTL:
            return cached_closes

    urls = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={binance_symbol}&interval={interval}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={binance_symbol}&interval={interval}&limit={limit}"
    ]
    for url in urls:
        try:
            res = requests.get(url, timeout=4)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) >= 20:
                    closes = [float(candle[4]) for candle in data]
                    _KLINE_CACHE[binance_symbol] = (now, closes)
                    return closes
        except Exception:
            continue
    return None


def calculate_wilders_rsi(closes, period=14):
    """Calculate standard Wilder's RSI from closing prices."""
    if len(closes) < period + 1:
        return 50.0

    deltas = np.diff(closes)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period

    if down == 0:
        return 100.0

    rs = up / down
    rsi = 100.0 - (100.0 / (1.0 + rs))

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
    """True recursive Exponential Moving Average (EMA)."""
    if not closes:
        return 0.0
    if len(closes) < period:
        return float(np.mean(closes))

    k = 2.0 / (period + 1.0)
    ema = float(np.mean(closes[:period]))
    for price in closes[period:]:
        ema = (price * k) + (ema * (1.0 - k))
    return float(ema)


def evaluate_market(trend: str, rsi: float, momentum: float, liquidity_usd: float, macd: float, macd_signal: float, price: float, binance_symbol: str = None) -> str:
    """
    Evaluate market using 15m Klines (Wilder's RSI + EMA20/EMA50) with smart fallback.
    """
    if liquidity_usd < 20000.0:
        return "HOLD"

    if binance_symbol:
        closes = fetch_klines(binance_symbol, interval="15m", limit=55)
        if closes and len(closes) >= 25:
            # Update latest close with real-time WebSocket price
            closes = closes[:-1] + [price]
            real_rsi = calculate_wilders_rsi(closes, period=14)
            ema20 = calculate_ema(closes, period=20)
            ema50 = calculate_ema(closes, period=50)

            # Long Setup: Bullish EMA alignment or strong bounce above EMA20
            if (price >= ema20 or ema20 >= ema50) and 28.0 <= real_rsi <= 72.0 and trend == "UP":
                return "LONG"
            # Short Setup: Bearish EMA alignment or breakdown below EMA20
            elif (price <= ema20 or ema20 <= ema50) and 28.0 <= real_rsi <= 72.0 and trend == "DOWN":
                return "SHORT"

    # Fallback momentum signal if Klines are warming up
    if trend == "UP" and rsi < 70.0 and momentum >= 0.6:
        return "LONG"
    elif trend == "DOWN" and rsi > 30.0 and momentum <= 0.4:
        return "SHORT"

    return "HOLD"
