"""
ESPTRADER - Bot Cuantitativo IQ Option SCRIPT VIP
Panel Web Admin, Integración Telegram y Monitoreo Segundo a Segundo.
"""

import uvicorn
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import Config
from core.iq_client import IQOptionClient
from core.telegram_bot import TelegramNotifier
from core.trading_engine import TradingEngine
from web.routes import router

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ESPTRADER")

# Instancias Globales
config = Config()
iq_client = IQOptionClient(
    email=config.IQ_EMAIL,
    password=config.IQ_PASSWORD,
    account_type=config.IQ_ACCOUNT_TYPE
)
telegram = TelegramNotifier(
    token=config.TELEGRAM_BOT_TOKEN,
    chat_id=config.TELEGRAM_CHAT_ID,
    admin_user=config.TELEGRAM_ADMIN_USER
)
engine = TradingEngine(config=config, iq_client=iq_client, telegram=telegram)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicio: lanzar loop asíncrono segundo a segundo
    logger.info("Iniciando ESPTrader Server...")
    logger.info(f"Telegram Bot Token: {config.TELEGRAM_BOT_TOKEN[:10]}... | Canal: {config.TELEGRAM_CHAT_ID}")
    logger.info(f"Acceso Web: http://localhost:{config.PORT}")
    
    # Iniciar conexión inicial IQ Option
    iq_client.connect()
    
    # Tarea en background
    task = asyncio.create_task(engine.run_loop())
    
    yield
    
    # Cierre
    logger.info("Deteniendo motor y cerrando conexiones...")
    engine.stop()
    task.cancel()

app = FastAPI(title="Trader 4 Less - Bot VIP", lifespan=lifespan)

# Estado global accesible en routers
app.state.config = config
app.state.iq_client = iq_client
app.state.telegram = telegram
app.state.engine = engine

# Archivos estáticos y rutas
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)

if __name__ == "__main__":
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=False)
