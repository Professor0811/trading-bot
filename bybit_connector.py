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
        self.ping_thread = None
        self.is_connected = False

        self.start_websocket()

    def send_heartbeat(self):
        """Bybit V5 requires a ping every 20 seconds to keep connection alive."""
        while True:
            time.sleep(20)
            if self.ws and self.is_connected:
                try:
                    self.ws.send(json.dumps({"op": "ping"}))
                except Exception:
                    pass

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            # Ignore pong responses
            if data.get("op") == "pong" or data.get("ret_msg") == "pong":
                return

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
        except Exception:
            pass

    def on_error(self, ws, error):
        print("[Bybit WS Error]:", error)

    def on_close(self, ws, close_status_code, close_msg):
        self.is_connected = False
        print("[Bybit WS Closed]. Reconnecting in 3 seconds...")
        time.sleep(3)
        self.start_websocket()

    def on_open(self, ws):
        self.is_connected = True
        print("[Bybit WS] Connected & Stream Authenticated ⚡")
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

        if not self.ping_thread:
            self.ping_thread = threading.Thread(target=self.send_heartbeat, daemon=True)
            self.ping_thread.start()

    def fetch_all_linear_tickers(self) -> list:
        if self.tickers_cache:
            return list(self.tickers_cache.values())

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


bybit_client = BybitConnector()
