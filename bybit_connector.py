import json
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
        urls = [
            "https://api.bytick.com/v5/market/tickers?category=linear",
            "https://api.bybit.com/v5/market/tickers?category=linear"
        ]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
        }

        for url in urls:
            try:
                res = requests.get(url, headers=headers, timeout=3)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("retCode") == 0:
                        items = data.get("result", {}).get("list", [])
                        if items:
                            return items
            except Exception:
                pass

        # High-Speed Failover Feed (Zero IP Block)
        try:
            f_res = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=3)
            if f_res.status_code == 200:
                raw_items = f_res.json()
                converted = []
                for r in raw_items:
                    sym = r.get("symbol", "")
                    if sym.endswith("USDT"):
                        converted.append({
                            "symbol": sym,
                            "lastPrice": float(r.get("lastPrice", 0.0)),
                            "turnover24h": float(r.get("quoteVolume", 0.0)),
                            "price24hPcnt": float(r.get("priceChangePercent", 0.0)) / 100.0
                        })
                return converted
        except Exception:
            pass

        return []

    def fetch_klines(self, symbol: str, interval: str = "15", limit: int = 40) -> list:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
        }
        
        url = f"https://api.bytick.com/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit={limit}"
        try:
            res = requests.get(url, headers=headers, timeout=3)
            if res.status_code == 200:
                data = res.json()
                if data.get("retCode") == 0:
                    raw_list = data.get("result", {}).get("list", [])
                    if raw_list:
                        raw_list.reverse()
                        return raw_list
        except Exception:
            pass

        binance_interval = "15m" if interval == "15" else ("1h" if interval in ["60", "1H"] else "15m")
        try:
            f_k = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={binance_interval}&limit={limit}", timeout=3)
            if f_k.status_code == 200:
                return f_k.json()
        except Exception:
            pass

        return []


bybit_client = BybitConnector()
