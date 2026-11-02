import requests

# Telegram Bot Credentials (ඔයාගේ Bot Token සහ Chat ID මෙහි ඇතුළත් කරන්න)
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID_HERE"

def send_telegram_alert(message: str):
    """
    Sends real-time trading alerts to a Telegram chat or channel.
    """
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print(f"Telegram Alert (Simulated): {message}")
        return True
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"🤖 **Trading Bot Alert**\n\n{message}",
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            print("Telegram alert sent successfully!")
            return True
        else:
            print(f"Failed to send Telegram alert: {response.text}")
            return False
    except Exception as e:
        print(f"Telegram Connection Error: {e}")
        return False

if __name__ == "__main__":
    print("Testing Telegram Notifier...")
    send_telegram_alert("Test alert from Autonomous Crypto Trading Bot!")