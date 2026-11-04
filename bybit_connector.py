import requests
import config

try:
    from pybit.unified_trading import HTTP
    pybit_available = True
except ImportError:
    pybit_available = False


class BybitConnector:
    def __init__(self):
        self.api_key = config.BYBIT_API_KEY
        self.api_secret = config.BYBIT_API_SECRET
        self.testnet = config.BYBIT_TESTNET
        self.client = None

        if pybit_available and self.api_key and self.api_secret:
            try:
                self.client = HTTP(
                    testnet=self.testnet,
                    api_key=self.api_key,
                    api_secret=self.api_secret
                )
                print("[Bybit] pybit V5 HTTP Client initialized.")
            except Exception as e:
                print("[Bybit Client Init Error]:", e)

    def fetch_all_linear_tickers(self) -> list:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"
        }

        # 1. Try Bybit V5 Direct first
        for url in [
            "https://api.bytick.com/v5/market/tickers?category=linear",
            "https://api.bybit.com/v5/market/tickers?category=linear"
        ]:
            try:
                res = requests.get(url, headers=headers, timeout=2.5)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("retCode") == 0:
                        items = data.get("result", {}).get("list", [])
                        if items:
                            return items
            except Exception:
                pass

        # 2. Primary Zero-Block Failover: Binance Vision Public Data CDN (100% US Cloud Allowed)
        try:
            v_res = requests.get("https://data-api.binance.vision/api/v3/ticker/24hr", headers=headers, timeout=4)
            if v_res.status_code == 200:
                raw_items = v_res.json()
                converted = []
                for r in raw_items:
                    sym = r.get("symbol", "")
                    if sym.endswith("USDT"):
                        last_p = float(r.get("lastPrice", 0.0) or 0.0)
                        q_vol = float(r.get("quoteVolume", 0.0) or 0.0)
                        pct = float(r.get("priceChangePercent", 0.0) or 0.0) / 100.0
                        if last_p > 0 and q_vol > 100000:
                            converted.append({
                                "symbol": sym,
                                "lastPrice": last_p,
                                "turnover24h": q_vol,
                                "price24hPcnt": pct
                            })
                if converted:
                    return converted
        except Exception as e:
            print("[Binance Vision Fallback Error]:", e)

        # 3. Secondary Failover: OKX Global Perpetual Swap Tickers (Zero US IP Block)
        try:
            okx_res = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP", headers=headers, timeout=4)
            if okx_res.status_code == 200:
                okx_data = okx_res.json().get("data", [])
                converted = []
                for r in okx_data:
                    inst_id = r.get("instId", "")  # e.g., BTC-USDT-SWAP
                    if "-USDT-SWAP" in inst_id:
                        sym = inst_id.replace("-USDT-SWAP", "USDT")
                        last_p = float(r.get("last", 0.0) or 0.0)
                        open_24h = float(r.get("open24h", last_p) or last_p)
                        vol_ccy = float(r.get("volCcy24h", 0.0) or 0.0) * last_p
                        pct = ((last_p - open_24h) / open_24h) if open_24h > 0 else 0.0
                        if last_p > 0:
                            converted.append({
                                "symbol": sym,
                                "lastPrice": last_p,
                                "turnover24h": vol_ccy,
                                "price24hPcnt": pct
                            })
                if converted:
                    return converted
        except Exception as e:
            print("[OKX Fallback Error]:", e)

        return []

    def fetch_klines(self, symbol: str, interval: str = "15", limit: int = 40) -> list:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"
        }

        # 1. Try Bybit V5 Klines
        url = f"https://api.bytick.com/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit={limit}"
        try:
            res = requests.get(url, headers=headers, timeout=2.5)
            if res.status_code == 200:
                data = res.json()
                if data.get("retCode") == 0:
                    raw_list = data.get("result", {}).get("list", [])
                    if raw_list:
                        raw_list.reverse()
                        return raw_list
        except Exception:
            pass

        # 2. Primary Zero-Block Klines: Binance Vision CDN (100% US Cloud Allowed)
        b_interval = "15m" if interval == "15" else ("1h" if interval in ["60", "1H"] else "15m")
        try:
            v_k = requests.get(
                f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={b_interval}&limit={limit}",
                headers=headers,
                timeout=3.5
            )
            if v_k.status_code == 200:
                return v_k.json()
        except Exception as e:
            print(f"[Kline Vision Fallback Error {symbol}]:", e)

        return []


bybit_client = BybitConnector()
