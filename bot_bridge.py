# ==============================================================================
# BOT BRIDGE: Read Fundamental Bias from Supabase Cloud DB
# ==============================================================================

import os
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_current_market_bias() -> dict:
    """Reads latest synthesized macro bias from Supabase market_bias table."""
    default_bias = {
        "composite_score": 0.0,
        "bias_label": "NEUTRAL",
        "is_news_freeze": False,
        "active_macro_event": None
    }

    if not DATABASE_URL:
        return default_bias

    try:
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)

        conn = psycopg2.connect(url, sslmode="require")
        cursor = conn.cursor()
        cursor.execute("SELECT composite_score, bias_label, is_news_freeze, active_macro_event FROM market_bias WHERE id = 1;")
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            return {
                "composite_score": float(row[0]),
                "bias_label": str(row[1]),
                "is_news_freeze": bool(row[2]),
                "active_macro_event": row[3]
            }
    except Exception as e:
        print(f"[Bot Bridge Read Error]: {e}")

    return default_bias


def should_block_trade(side: str) -> tuple[bool, str]:
    """Pre-trade fundamental gatekeeper."""
    bias = get_current_market_bias()

    # 1. Macro News Freeze (CPI, FOMC, Fed Rate cuts)
    if bias.get("is_news_freeze", False):
        event = bias.get("active_macro_event") or "High-Impact Macro Release"
        return True, f"Blocked by Macro News Freeze: {event}"

    score = bias.get("composite_score", 0.0)

    # 2. Market එක Strongly Bearish නම් LONG block කරයි
    if side.upper() == "LONG" and score <= -50.0:
        return True, f"Blocked LONG: Market Heavily Bearish ({score:+.1f})"

    # 3. Market එක Strongly Bullish නම් SHORT block කරයි
    if side.upper() == "SHORT" and score >= 50.0:
        return True, f"Blocked SHORT: Market Heavily Bullish ({score:+.1f})"

    return False, "Allowed"
