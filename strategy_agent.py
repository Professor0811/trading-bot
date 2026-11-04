import numpy as np
from bybit_connector import bybit_client


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
    Bybit BTC Crash Guard:
    Analyzes BTCUSDT 15m and 1h trends on Bybit.
    """
    try:
        klines_15m = bybit_client.fetch_klines("BTCUSDT", interval="15", limit=10)
        if len(klines_15m) >= 4:
            recent_high = max(float(k[2]) for k in klines_15m[-4:])
            current_close = float(klines_15m[-1][4])
            drop_pct = ((current_close - recent_high) / recent_high) * 100.0

            if drop_pct <= -1.2:
                return {
                    "regime": "CRASH",
                    "allow_long": False,
                    "allow_short": True,
                    "reason": f"Bybit BTC Fast Drop {drop_pct:.2f}% (Dump Alert)",
                    "btc_drop_pct": round(drop_pct, 2)
                }

        klines_1h = bybit_client.fetch_klines("BTCUSDT", interval="60", limit=30)
        if len(klines_1h) >= 20:
            closes_1h = [float(k[4]) for k in klines_1h]
            ema20 = calculate_ema(closes_1h, 20)
            current_p = closes_1h[-1]

            if current_p < ema20 * 0.985:
                return {
                    "regime": "BEAR",
                    "allow_long": False,
                    "allow_short": True,
                    "reason": "Bybit BTC Below 1H EMA20 (Macro Downtrend)",
                    "btc_drop_pct": round(((current_p - ema20) / ema20) * 100.0, 2)
                }

    except Exception as e:
        print("[Bybit BTC Regime Error]:", e)

    return {
        "regime": "STABLE",
        "allow_long": True,
        "allow_short": True,
        "reason": "Bybit BTC Stable / Normal Volatility",
        "btc_drop_pct": 0.0
    }


def evaluate_market_with_atr(symbol: str, trend: str, current_price: float):
    klines_15m = bybit_client.fetch_klines(symbol, interval="15", limit=30)
    if not klines_15m or len(klines_15m) < 20:
        return "NONE", (current_price * 0.01), 1.0, "NEUTRAL"

    atr_val = calculate_atr(klines_15m)

    # Volume spike check (20-SMA)
    volumes = [float(k[5]) for k in klines_15m]
    current_vol = volumes[-1]
    avg_vol_20 = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else float(np.mean(volumes))
    vol_ratio = (current_vol / (avg_vol_20 + 1e-9))

    # 1H Macro Alignment
    klines_1h = bybit_client.fetch_klines(symbol, interval="60", limit=30)
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

    signal = "NONE"
    if vol_ratio >= 1.10:
        if trend == "UP" and ema9_15m > ema21_15m and macro_trend in ["BULL", "NEUTRAL"]:
            signal = "LONG"
        elif trend == "DOWN" and ema9_15m < ema21_15m and macro_trend in ["BEAR", "NEUTRAL"]:
            signal = "SHORT"

    return signal, atr_val, vol_ratio, macro_trend
