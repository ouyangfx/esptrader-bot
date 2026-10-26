import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # IQ Option Settings
    IQ_EMAIL = os.getenv("IQ_EMAIL", "")
    IQ_PASSWORD = os.getenv("IQ_PASSWORD", "")
    IQ_ACCOUNT_TYPE = os.getenv("IQ_ACCOUNT_TYPE", "PRACTICE").upper()

    # Bot Trading Parameters - 10 Normal + 10 OTC Pairs
    NORMAL_PAIRS = [
        "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "AUDUSD",
        "USDCAD", "USDCHF", "EURGBP", "NZDUSD", "GBPJPY"
    ]
    OTC_PAIRS = [
        "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "EURJPY-OTC", "AUDUSD-OTC",
        "USDCAD-OTC", "USDCHF-OTC", "NZDUSD-OTC", "EURGBP-OTC", "GBPJPY-OTC"
    ]
    ALL_AVAILABLE_PAIRS = NORMAL_PAIRS + OTC_PAIRS

    _pairs_raw = os.getenv("TRADING_PAIRS", "EURUSD,GBPUSD,USDJPY,EURJPY,EURUSD-OTC,GBPUSD-OTC")
    TRADING_PAIRS = [p.strip().upper() for p in _pairs_raw.split(",") if p.strip()]
    TIMEFRAME = int(os.getenv("TIMEFRAME", "60"))  # 60s (1m) or 300s (5m)
    EXPIRATION_TIME = int(os.getenv("EXPIRATION_TIME", "1"))  # 1 min
    TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", "2.0"))
    MARTINGALE_STEPS = int(os.getenv("MARTINGALE_STEPS", "1"))
    MARTINGALE_MULTIPLIER = float(os.getenv("MARTINGALE_MULTIPLIER", "2.2"))
    STOP_LOSS = float(os.getenv("STOP_LOSS", "20.0"))
    TAKE_PROFIT = float(os.getenv("TAKE_PROFIT", "50.0"))

    # Telegram Credentials
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8548283354:AAEn6xmBRFOn-pwRxT3pSYClbVQerzrKqAM")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@traderfxapp")
    TELEGRAM_ADMIN_USER = os.getenv("TELEGRAM_ADMIN_USER", "ouyangfx")

    # Web Admin Credentials & Security
    ADMIN_USER = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASS = os.getenv("ADMIN_PASS", "TraderVIP2026!")
    SECRET_KEY = os.getenv("SECRET_KEY", "super_secret_session_key_esptrader")
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
