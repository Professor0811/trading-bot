import time
import requests
import numpy as np

# Separate caches for 15m (60s TTL) and 1h (300s TTL) klines
_KLINE_CACHE_15M = {}
_KLINE_CACHE_1H = {}
CACHE_TTL_15M = 60
CACHE_TTL_1H = 300


def fetch_full_klines(binance_symbol: str, interval="15m", limit=55):
    """
    Fetch full OHLCV klines (High, Low, Close, Volume) from Binance Vision API
    with interval-aware smart caching.
    """
    now = time.time()
    cache = _KLINE_CACHE_1H if interval == "1h" else _KLINE_CACHE_15M
    ttl = CACHE_TTL_1H if interval == "1h" else CACHE_TTL_15M

    if binance_symbol in cache:
        cached_time, cached_data = cache[binance_symbol]
        if now - cached_time < ttl:
            return cached_data

    urls = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={binance_symbol}&interval={interval}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={binance_symbol}&interval={interval}&limit={limit}"
    ]
    for url in urls:
        try:
            res = requests.get(url, timeout=4)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) >= 25:
                    highs = [float(c[2]) for c in data]
                    lows = [float(c[3]) for c in data]
                    closes = [float(c[4]) for c in data]
                    volumes = [float(c[5]) for c in data]
                    result = {
                        "high": highs,
                        "low": lows,
                        "close": closes,
                        "volume": volumes
                    }
                    cache[binance_symbol] = (now, result)
                    return result
        except Exception:
            continue
    return None


def calculate_atr(highs, lows, closes, period=14):
    """Calculate 14-period Average True Range (ATR)."""
    if len(closes) < period + 1:
        return closes[-1] * 0.01

    tr_list = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i - 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)

    atr = np.mean(tr_list[:period])
    for tr in tr_list[period:]:
        atr = (atr * (period - 1) + tr) / period

    return float(atr)


def calculate_volume_ratio(volumes, period=20):
    """
    Compare recent candle volume against the 20-period Volume SMA.
    Uses max of current forming candle and last closed candle.
    """
    if not volumes or len(volumes) < period + 2:
        return 1.2

    baseline_vols = volumes[-(period + 2):-2]
    avg_vol = float(np.mean(baseline_vols)) if baseline_vols else 1.0
    if avg_vol <= 0:
        return 1.2

    recent_active_vol = max(volumes[-1], volumes[-2])
    return round(recent_active_vol / avg_vol, 2)


def calculate_wilders_rsi(closes, period=14):
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
    if not closes:
        return 0.0
    if len(closes) < period:
        return float(np.mean(closes))

    k = 2.0 / (period + 1.0)
    ema = float(np.mean(closes[:period]))
    for price in closes[period:]:
        ema = (price * k) + (ema * (1.0 - k))
    return float(ema)


def get_1h_macro_trend(binance_symbol: str, current_price: float) -> str:
    """
    Determine 1-Hour (1H) Macro Trend using 1H EMA 20 and EMA 50.
    Returns 'BULL', 'BEAR', or 'NEUTRAL'.
    """
    k_1h = fetch_full_klines(binance_symbol, interval="1h", limit=55)
    if not k_1h or len(k_1h["close"]) < 25:
        return "NEUTRAL"

    closes_1h = k_1h["close"][:-1] + [current_price]
    ema20_1h = calculate_ema(closes_1h, period=20)
    ema50_1h = calculate_ema(closes_1h, period=50)

    if current_price >= ema50_1h and ema20_1h >= ema50_1h * 0.998:
        return "BULL"
    elif current_price <= ema50_1h and ema20_1h <= ema50_1h * 1.002:
        return "BEAR"
    elif current_price >= ema20_1h:
        return "BULL"
    else:
        return "BEAR"


def evaluate_market_with_atr(trend: str, price: float, binance_symbol: str = None) -> tuple:
    """
    Returns (signal, atr_value, volume_ratio, macro_1h_trend)
    Combines 15m Klines (RSI + EMA + Volume Spike) with 1H Macro Trend alignment.
    """
    default_atr = price * 0.01

    if binance_symbol:
        k_data = fetch_full_klines(binance_symbol, interval="15m", limit=55)
        if k_data and len(k_data["close"]) >= 25:
            closes = k_data["close"][:-1] + [price]
            highs = k_data["high"]
            lows = k_data["low"]
            volumes = k_data.get("volume", [])

            real_rsi = calculate_wilders_rsi(closes, period=14)
            ema20 = calculate_ema(closes, period=20)
            ema50 = calculate_ema(closes, period=50)
            atr_val = calculate_atr(highs, lows, closes, period=14)
            vol_ratio = calculate_volume_ratio(volumes, period=20)

            atr_val = max(price * 0.006, min(atr_val, price * 0.025))

            # 1. Fakeout Protection: Require Volume Ratio >= 1.10x
            if vol_ratio < 1.10:
                return "HOLD", atr_val, vol_ratio, "NEUTRAL"

            # 2. Check 1H Macro Trend Alignment
            macro_trend = get_1h_macro_trend(binance_symbol, price)

            # 3. 15m + 1H Aligned Entry Signals
            is_15m_long = (price >= ema20 or ema20 >= ema50) and 28.0 <= real_rsi <= 72.0 and trend == "UP"
            is_15m_short = (price <= ema20 or ema20 <= ema50) and 28.0 <= real_rsi <= 72.0 and trend == "DOWN"

            if is_15m_long and macro_trend in ["BULL", "NEUTRAL"]:
                return "LONG", atr_val, vol_ratio, f"1H {macro_trend}"
            elif is_15m_short and macro_trend in ["BEAR", "NEUTRAL"]:
                return "SHORT", atr_val, vol_ratio, f"1H {macro_trend}"

            return "HOLD", atr_val, vol_ratio, f"1H {macro_trend}"

    return "HOLD", default_atr, 1.0, "NEUTRAL"
