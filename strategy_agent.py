import time
import requests
import numpy as np

_KLINE_CACHE = {}
CACHE_TTL = 60  # Cache 15m klines for 60 seconds per symbol


def fetch_full_klines(binance_symbol: str, interval="15m", limit=55):
    """
    Fetch full OHLCV klines (High, Low, Close, Volume) from Binance Vision API.
    Returns dict with 'high', 'low', 'close', 'volume' lists or None.
    """
    now = time.time()
    if binance_symbol in _KLINE_CACHE:
        cached_time, cached_data = _KLINE_CACHE[binance_symbol]
        if now - cached_time < CACHE_TTL:
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
                    _KLINE_CACHE[binance_symbol] = (now, result)
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
    Uses max of current forming candle and last closed candle to avoid early-minute bias.
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


def evaluate_market_with_atr(trend: str, price: float, binance_symbol: str = None) -> tuple:
    """
    Returns (signal, atr_value, volume_ratio)
    Filters out low-volume fakeouts by requiring Volume Ratio >= 1.10x of 20-period SMA.
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

            # Cap ATR between 0.6% and 2.5% of price
            atr_val = max(price * 0.006, min(atr_val, price * 0.025))

            # Fakeout Protection: Reject setups with dead volume (< 1.10x average volume)
            if vol_ratio < 1.10:
                return "HOLD", atr_val, vol_ratio

            if (price >= ema20 or ema20 >= ema50) and 28.0 <= real_rsi <= 72.0 and trend == "UP":
                return "LONG", atr_val, vol_ratio
            elif (price <= ema20 or ema20 <= ema50) and 28.0 <= real_rsi <= 72.0 and trend == "DOWN":
                return "SHORT", atr_val, vol_ratio

            return "HOLD", atr_val, vol_ratio

    return "HOLD", default_atr, 1.0
