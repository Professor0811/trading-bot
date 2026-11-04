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
                print("[Bybit] pybit V5 HTTP client initialized successfully.")
            except Exception as e:
                print("[Bybit Client Init Error]:", e)

    def fetch_all_linear_tickers(self) -> list:
        """
        Fetches all 300+ Linear USDT Perpetual pairs from Bybit V5 Public API.
        Zero API Key requirement for public market tickers.
        """
        domain = "https://api-testnet.bybit.com" if self.testnet else "https://api.bybit.com"
        url = f"{domain}/v5/market/tickers?category=linear"
        try:
            res = requests.get(url, timeout=6)
            if res.status_code == 200:
                data = res.json()
                if data.get("retCode") == 0:
                    return data.get("result", {}).get("list", [])
        except Exception as e:
            print("[Bybit Tickers Fetch Error]:", e)
        return []

    def fetch_klines(self, symbol: str, interval: str = "15", limit: int = 40) -> list:
        """
        Fetches official Bybit V5 klines for a given linear symbol.
        Intervals: 15 (15m), 60 (1h).
        Returns list of candles: [startTime, openPrice, highPrice, lowPrice, closePrice, volume, turnover]
        """
        domain = "https://api-testnet.bybit.com" if self.testnet else "https://api.bybit.com"
        url = f"{domain}/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit={limit}"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data.get("retCode") == 0:
                    raw_list = data.get("result", {}).get("list", [])
                    # Bybit returns klines in reverse chronological order (newest first). Reverse it.
                    raw_list.reverse()
                    return raw_list
        except Exception as e:
            print(f"[Bybit Klines Error for {symbol}]:", e)
        return []


bybit_client = BybitConnector()
