import requests
import numpy as np


def fetch_klines(symbol: str, interval: str = "15m", limit: int = 50):
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"[Strategy Error] Fetching klines for {symbol}:", e)
    return []


def calculate_atr(klines):
    if len(klines) < 15:
        return 0.0
    tr_list = []
    for i in range(1, len(klines)):
        high = float(klines[i][2])
        low = float(klines[i][3])
        prev_close = float(klines[i - 1][4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
    return float(np.mean(tr_list[-14:]))


def calculate_ema(prices, period: int):
    if len(prices) < period:
        return float(prices[-1])
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    a = np.convolve(prices, weights, mode='full')[:len(prices)]
    a[:period] = a[period]
    return float(a[-1])


def check_btc_market_regime() -> dict:
    """
    BTC Crash Detector:
    Analyzes BTC 15m and 1H trends.
    If BTC drops >= 1.2% in the last 15-30m or EMA breaks down, flags regime as CRASH/BEAR.
    """
    try:
        # Check 15m klines for immediate volatility / dump
        klines_15m = fetch_klines("BTCUSDT", interval="15m", limit=10)
        if len(klines_15m) >= 4:
            recent_high = max(float(k[2]) for k in klines_15m[-4:])
            current_close = float(klines_15m[-1][4])
            drop_pct = ((current_close - recent_high) / recent_high) * 100.0

            # If sudden dump >= 1.2% detected
            if drop_pct <= -1.2:
                return {
                    "regime": "CRASH",
                    "allow_long": False,
                    "allow_short": True,
                    "reason": f"BTC Fast Drop {drop_pct:.2f}% (Dump Alert)",
                    "btc_drop_pct": round(drop_pct, 2)
                }

        # Check 1H trend alignment
        klines_1h = fetch_klines("BTCUSDT", interval="1h", limit=30)
        if len(klines_1h) >= 20:
            closes_1h = [float(k[4]) for k in klines_1h]
            ema20 = calculate_ema(closes_1h, 20)
            current_p = closes_1h[-1]

            if current_p < ema20 * 0.985:  # BTC trading >1.5% below 1H EMA20
                return {
                    "regime": "BEAR",
                    "allow_long": False,
                    "allow_short": True,
                    "reason": "BTC Below 1H EMA20 (Macro Downtrend)",
                    "btc_drop_pct": round(((current_p - ema20) / ema20) * 100.0, 2)
                }

    except Exception as e:
        print("[BTC Regime Error]:", e)

    return {
        "regime": "STABLE",
        "allow_long": True,
        "allow_short": True,
        "reason": "BTC Stable / Normal Volatility",
        "btc_drop_pct": 0.0
    }


def evaluate_market_with_atr(trend: str, price: float, bin_sym: str):
    klines_15m = fetch_klines(bin_sym, interval="15m", limit=30)
    if not klines_15m or len(klines_15m) < 20:
        return "NONE", (price * 0.01), 1.0, "NEUTRAL"

    atr_val = calculate_atr(klines_15m)

    # Volume spike check (20-SMA)
    volumes = [float(k[5]) for k in klines_15m]
    current_vol = volumes[-1]
    avg_vol_20 = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else float(np.mean(volumes))
    vol_ratio = (current_vol / (avg_vol_20 + 1e-9))

    # 1H Macro Alignment
    klines_1h = fetch_klines(bin_sym, interval="1h", limit=30)
    macro_trend = "NEUTRAL"
    if len(klines_1h) >= 20:
        closes_1h = [float(k[4]) for k in klines_1h]
        ema20_1h = calculate_ema(closes_1h, 20)
        if closes_1h[-1] > ema20_1h:
            macro_trend = "BULL"
        elif closes_1h[-1] < ema20_1h:
            macro_trend = "BEAR"

    # 15m Trend & EMA Signals
    closes_15m = [float(k[4]) for k in klines_15m]
    ema9_15m = calculate_ema(closes_15m, 9)
    ema21_15m = calculate_ema(closes_15m, 21)

    # Signal conditions with MTF & Volume requirements
    signal = "NONE"
    if vol_ratio >= 1.10:
        if trend == "UP" and ema9_15m > ema21_15m and macro_trend in ["BULL", "NEUTRAL"]:
            signal = "LONG"
        elif trend == "DOWN" and ema9_15m < ema21_15m and macro_trend in ["BEAR", "NEUTRAL"]:
            signal = "SHORT"

    return signal, atr_val, vol_ratio, macro_trend
