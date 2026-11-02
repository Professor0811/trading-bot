import urllib.request
import urllib.parse
import json

TELEGRAM_BOT_TOKEN = "9170772758:AAEsidX-dJkZ7A0K85JZdx0A-mov3uqIm4w"
TELEGRAM_CHAT_ID = "5449445315"

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not configured.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")
        return None