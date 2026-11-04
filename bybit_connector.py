import json
import threading
import time
import websocket
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
        self.tickers_cache = {}
        self.ws = None
        self.ws_thread = None

        # Start Bybit V5 Public WebSocket in Background
        self.start_websocket()

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            topic = data.get("topic", "")
            if topic.startswith("tickers."):
                tick_data = data.get("data", {})
                sym = tick_data.get("symbol")
                if sym:
                    if sym not in self.tickers_cache:
                        self.tickers_cache[sym] = {
                            "symbol": sym,
                            "lastPrice": 0.0,
                            "turnover24h": 0.0,
                            "price24hPcnt": 0.0
                        }
                    
                    if "lastPrice" in tick_data:
                        self.tickers_cache[sym]["lastPrice"] = float(tick_data["lastPrice"])
                    if "turnover24h" in tick_data:
                        self.tickers_cache[sym]["turnover24h"] = float(tick_data["turnover24h"])
                    if "price24hPcnt" in tick_data:
                        self.tickers_cache[sym]["price24hPcnt"] = float(tick_data["price24hPcnt"])
        except Exception as e:
            pass

    def on_error(self, ws, error):
        print("[Bybit WS Error]:", error)

    def on_close(self, ws, close_status_code, close_msg):
        print("[Bybit WS Closed]. Reconnecting in 3 seconds...")
        time.sleep(3)
        self.start_websocket()

    def on_open(self, ws):
        print("[Bybit WS] Connected to Bybit V5 Public Linear Stream ⚡")
        # Subscribe to all Linear USDT perpetual tickers
        sub_msg = {
            "op": "subscribe",
            "args": [
                "tickers.BTCUSDT", "tickers.ETHUSDT", "tickers.SOLUSDT", "tickers.XRPUSDT",
                "tickers.DOGEUSDT", "tickers.ADAUSDT", "tickers.AVAXUSDT", "tickers.SUIUSDT",
                "tickers.LINKUSDT", "tickers.NEARUSDT", "tickers.APTUSDT", "tickers.PEPEUSDT",
                "tickers.SHIBUSDT", "tickers.ARBUSDT", "tickers.OPUSDT", "tickers.FETUSDT",
                "tickers.INJUSDT", "tickers.TIAUSDT", "tickers.RENDERUSDT", "tickers.WIFUSDT",
                "tickers.BONKUSDT", "tickers.FLOKIUSDT", "tickers.KASUSDT", "tickers.ENAUSDT",
                "tickers.ORDIUSDT", "tickers.STXUSDT", "tickers.RUNEUSDT", "tickers.GALAUSDT"
            ]
        }
        ws.send(json.dumps(sub_msg))

    def start_websocket(self):
        ws_url = "wss://stream.bybit.com/v5/public/linear"
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        self.ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.ws_thread.start()

    def fetch_all_linear_tickers(self) -> list:
        # If WebSocket already cached items, return immediately (Zero Latency)
        if self.tickers_cache:
            return list(self.tickers_cache.values())

        # Fallback to public endpoints
        url = "https://api.bytick.com/v5/market/tickers?category=linear"
        try:
            res = requests.get(url, timeout=3)
            if res.status_code == 200:
                data = res.json()
                if data.get("retCode") == 0:
                    return data.get("result", {}).get("list", [])
        except Exception:
            pass
        return list(self.tickers_cache.values())

    def fetch_klines(self, symbol: str, interval: str = "15", limit: int = 40) -> list:
        # For Klines, if direct Bybit blocked, fetch directly or use clean Kline fallback
        url = f"https://api.bytick.com/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit={limit}"
        try:
            res = requests.get(url, timeout=3)
            if res.status_code == 200:
                data = res.json()
                if data.get("retCode") == 0:
                    raw_list = data.get("result", {}).get("list", [])
                    raw_list.reverse()
                    return raw_list
        except Exception:
            pass
        return []


bybit_client = BybitConnector()import requests
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
