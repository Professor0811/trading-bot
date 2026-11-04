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

        # Standard headers to prevent Cloudfront 403 blocks on Render IPs
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }

        # Always use Mainnet global mirror (api.bytick.com) first for real market data
        self.market_domains = [
            "https://api.bytick.com",
            "https://api.bybit.com",
            "https://api-testnet.bybit.com"
        ]

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
        Uses api.bytick.com failover to bypass US Cloud IP restrictions.
        """
        for domain in self.market_domains:
            url = f"{domain}/v5/market/tickers?category=linear"
            try:
                res = requests.get(url, headers=self.headers, timeout=6)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("retCode") == 0:
                        items = data.get("result", {}).get("list", [])
                        if items:
                            return items
                else:
                    print(f"[Bybit Warning] {domain} returned HTTP {res.status_code}")
            except Exception as e:
                print(f"[Bybit Tickers Failover] {domain} error:", e)
        return []

    def fetch_klines(self, symbol: str, interval: str = "15", limit: int = 40) -> list:
        """
        Fetches official Bybit V5 klines for a given linear symbol.
        """
        for domain in self.market_domains:
            url = f"{domain}/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit={limit}"
            try:
                res = requests.get(url, headers=self.headers, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("retCode") == 0:
                        raw_list = data.get("result", {}).get("list", [])
                        if raw_list:
                            raw_list.reverse()
                            return raw_list
            except Exception as e:
                print(f"[Bybit Klines Failover for {symbol}]:", e)
        return []


bybit_client = BybitConnector()
