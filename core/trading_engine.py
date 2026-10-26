"""
Motor Principal de Trading y Monitoreo Segundo a Segundo
Implementa la máquina de estados:
1. SEARCHING: Escaneo continuo de señales con SCRIPT VIP.
2. CONFIRMING: Espera de la vela siguiente a favor de la señal con monitoreo segundo a segundo.
3. IN_TRADE: Ejecución en el segundo 00 con expiración a 1m y monitoreo hasta el cierre.
4. RESULT: Verificación de resultado (ITM/OTM), martingala y notificación.
"""

import time
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from core.indicator import ScriptVipIndicator
from core.iq_client import IQOptionClient
from core.telegram_bot import TelegramNotifier

logger = logging.getLogger(__name__)

class TradingEngine:
    def __init__(self, config, iq_client: IQOptionClient, telegram: TelegramNotifier):
        self.config = config
        self.iq = iq_client
        self.telegram = telegram
        self.indicator = ScriptVipIndicator()
        
        # Estado del Bot
        self.is_running = False
        self.active_pair = self.config.TRADING_PAIRS[0] if self.config.TRADING_PAIRS else "EURUSD"
        self.timeframe = self.config.TIMEFRAME
        self.expiration = self.config.EXPIRATION_TIME
        self.base_amount = self.config.TRADE_AMOUNT
        self.current_amount = self.config.TRADE_AMOUNT
        self.martingale_steps = self.config.MARTINGALE_STEPS
        self.martingale_multiplier = self.config.MARTINGALE_MULTIPLIER
        self.current_martingale_step = 0
        
        # Máquina de estados
        # Estados: 'SEARCHING', 'CONFIRMING', 'IN_TRADE'
        self.state = "SEARCHING"
        self.pending_signal = None  # {'pair': 'EURUSD', 'direction': 'CALL', 'signal_time': '...', 'candle_from': 123}
        self.current_trade = None   # {'id': 123, 'pair': 'EURUSD', 'direction': 'CALL', 'entry_time': '...', 'entry_price': 1.08, 'start_ts': 123}
        
        # Historial y Estadísticas
        self.trade_history: List[Dict[str, Any]] = []
        self.session_stats = {
            "wins": 0,
            "losses": 0,
            "equals": 0,
            "net_profit": 0.0,
            "total_trades": 0,
            "winrate": 0.0
        }
        
        # Para streaming WebSocket a clientes web
        self.websocket_listeners = set()
        self.last_candle_analyzed_time = 0
        self.current_status_message = "Bot detenido"
        self.current_tick_price = 0.0
        self.seconds_left_in_candle = 0

    def start(self) -> Tuple[bool, str]:
        if self.is_running:
            return True, "El bot ya está en ejecución."
        
        success, msg = self.iq.connect()
        self.is_running = True
        self.state = "SEARCHING"
        self.current_amount = self.base_amount
        self.current_martingale_step = 0
        self.current_status_message = "Bot iniciado - Monitoreando mercado..."
        
        balance = self.iq.get_balance()
        self.telegram.notify_bot_status(True, self.active_pair, self.iq.account_type, balance)
        logger.info(f"Bot iniciado en {self.active_pair}. Timeframe: {self.timeframe}s")
        return True, "Bot encendido exitosamente."

    def stop(self) -> Tuple[bool, str]:
        if not self.is_running:
            return True, "El bot ya está detenido."
        
        self.is_running = False
        self.state = "SEARCHING"
        self.pending_signal = None
        self.current_status_message = "Bot detenido por el usuario."
        
        balance = self.iq.get_balance()
        self.telegram.notify_bot_status(False, self.active_pair, self.iq.account_type, balance)
        logger.info("Bot detenido.")
        return True, "Bot apagado correctamente."

    async def broadcast_status(self):
        """Envía el estado segundo a segundo a los clientes conectados por WebSocket."""
        data = {
            "is_running": self.is_running,
            "state": self.state,
            "pair": self.active_pair,
            "timeframe": self.timeframe,
            "seconds_left": self.seconds_left_in_candle,
            "tick_price": self.current_tick_price,
            "status_message": self.current_status_message,
            "balance": self.iq.get_balance(),
            "account_type": self.iq.account_type,
            "is_simulation": self.iq.is_simulation,
            "pending_signal": self.pending_signal,
            "current_trade": self.current_trade,
            "stats": self.session_stats,
            "history": self.trade_history[-15:] # Últimas 15 operaciones
        }
        dead_clients = set()
        for ws in self.websocket_listeners:
            try:
                await ws.send_json(data)
            except Exception:
                dead_clients.add(ws)
        self.websocket_listeners.difference_update(dead_clients)

    async def run_loop(self):
        """Bucle infinito asíncrono con control segundo a segundo."""
        logger.info("Iniciando bucle de control segundo a segundo...")
        while True:
            try:
                if self.is_running:
                    await self._tick()
                else:
                    self.seconds_left_in_candle = 0
                    self.current_status_message = "Bot detenido - Esperando activación en el panel admin"
                
                await self.broadcast_status()
            except Exception as e:
                logger.error(f"Error en tick de TradingEngine: {e}", exc_info=True)
            
            await asyncio.sleep(1.0)

    async def _tick(self):
        server_ts = self.iq.get_server_timestamp()
        dt_server = datetime.fromtimestamp(server_ts)
        time_str = dt_server.strftime("%H:%M:%S")
        
        # Segundos restantes para que cierre la vela actual
        self.seconds_left_in_candle = self.timeframe - (server_ts % self.timeframe)
        if self.seconds_left_in_candle == self.timeframe:
            self.seconds_left_in_candle = 0

        # Obtener datos de velas recientes (60 velas)
        candles = self.iq.get_candles(self.active_pair, self.timeframe, 60)
        if not candles:
            self.current_status_message = f"[{time_str}] Obteniendo velas de {self.active_pair}..."
            return

        latest_candle = candles[-1]
        self.current_tick_price = float(latest_candle.get('close', 0.0))

        # =========================================================
        # ESTADO 1: SEARCHING (Buscando la señal 'SCRIPT VIP')
        # =========================================================
        if self.state == "SEARCHING":
            self.current_status_message = f"[{time_str}] Buscando señal VIP en {self.active_pair} ({self.timeframe}s) - Vela: {self.seconds_left_in_candle}s restantes"
            
            # Analizamos cuando una vela acaba de cerrar (segundo 0 o 1 de una nueva vela)
            # O comprobamos la última vela cerrada (candles[-2])
            closed_candle = candles[-2]
            closed_candle_time = closed_candle.get('from', 0)
            
            if closed_candle_time != self.last_candle_analyzed_time:
                # Velas hasta la última cerrada
                analysis = self.indicator.analyze_candles(candles[:-1])
                self.last_candle_analyzed_time = closed_candle_time
                
                if analysis.get('signal'):
                    direction = analysis['signal']  # 'CALL' o 'PUT'
                    candle_dt_str = datetime.fromtimestamp(closed_candle_time).strftime("%H:%M:%S")
                    
                    self.pending_signal = {
                        "pair": self.active_pair,
                        "direction": direction,
                        "detected_at": time_str,
                        "candle_time": candle_dt_str,
                        "signal_candle_from": closed_candle_time,
                        "confirm_candle_from": latest_candle.get('from', 0)
                    }
                    self.state = "CONFIRMING"
                    tf_label = "1M" if self.timeframe == 60 else f"{self.timeframe//60}M"
                    self.current_status_message = f"¡SEÑAL {direction} DETECTADA! Esperando vela de confirmación a favor..."
                    
                    logger.info(f"Señal detectada: {self.active_pair} {direction}. Esperando confirmación.")
                    # Notificar a Telegram
                    self.telegram.notify_pre_signal(self.active_pair, direction, tf_label, candle_dt_str)

        # =========================================================
        # ESTADO 2: CONFIRMING (Esperando vela a favor)
        # =========================================================
        elif self.state == "CONFIRMING":
            direction = self.pending_signal["direction"]
            self.current_status_message = (
                f"[{time_str}] CONFIRMANDO SEÑAL {direction} en {self.active_pair}: "
                f"Quedan {self.seconds_left_in_candle}s para evaluar la vela."
            )
            
            # La vela confirmatoria es la actual que está corriendo.
            # Cuando falte <= 1 segundo para cerrar (segundo 59 -> 00) evaluamos si fue a favor:
            if self.seconds_left_in_candle <= 1:
                confirm_candle = latest_candle
                c_open = confirm_candle['open']
                c_close = confirm_candle['close']
                
                is_confirmed = False
                reason = ""
                
                if direction == "CALL":
                    if c_close > c_open:
                        is_confirmed = True
                    else:
                        reason = f"Vela bajista/doji (Open: {c_open}, Close: {c_close})"
                elif direction == "PUT":
                    if c_close < c_open:
                        is_confirmed = True
                    else:
                        reason = f"Vela alcista/doji (Open: {c_open}, Close: {c_close})"
                
                if is_confirmed:
                    # ¡CONFIRMADA! Entramos en el segundo exacto 00 de la siguiente vela
                    entry_time_str = datetime.fromtimestamp(server_ts + 1).strftime("%H:%M:%S")
                    trade_amount = self.current_amount
                    
                    logger.info(f"¡Vela confirmada! Ejecutando {direction} en {self.active_pair} a las {entry_time_str}")
                    
                    ok, order_id, msg = self.iq.buy_option(self.active_pair, trade_amount, direction, self.expiration)
                    if ok:
                        self.current_trade = {
                            "id": order_id,
                            "pair": self.active_pair,
                            "direction": direction,
                            "entry_time": entry_time_str,
                            "entry_price": c_close,
                            "amount": trade_amount,
                            "expiration": self.expiration,
                            "start_ts": server_ts,
                            "end_ts": server_ts + (self.expiration * 60)
                        }
                        self.state = "IN_TRADE"
                        self.telegram.notify_entry(
                            pair=self.active_pair,
                            direction=direction,
                            entry_time=entry_time_str,
                            entry_price=c_close,
                            expiration=self.expiration,
                            amount=trade_amount
                        )
                    else:
                        self.current_status_message = f"Error al abrir orden: {msg}"
                        self.state = "SEARCHING"
                        self.pending_signal = None
                else:
                    logger.info(f"Señal no confirmada: {reason}")
                    self.telegram.notify_confirmation_failed(self.active_pair, direction, reason)
                    self.state = "SEARCHING"
                    self.pending_signal = None

        # =========================================================
        # ESTADO 3: IN_TRADE (Operación abierta a 1 minuto)
        # =========================================================
        elif self.state == "IN_TRADE":
            remaining = self.current_trade["end_ts"] - server_ts
            trade_dir = self.current_trade["direction"]
            self.current_status_message = (
                f"[{time_str}] OPERACIÓN EN CURSO: {self.active_pair} {trade_dir} "
                f"${self.current_trade['amount']} - Cierre en: {max(0, remaining)}s"
            )
            
            # Al llegar al segundo de finalización
            if remaining <= 0:
                self.current_status_message = f"[{time_str}] Verificando resultado de operación..."
                await asyncio.sleep(1.5)  # Breve pausa para consolidación del broker
                
                order_id = self.current_trade["id"]
                result, profit, _, _ = self.iq.check_result(order_id)
                close_time_str = datetime.fromtimestamp(self.iq.get_server_timestamp()).strftime("%H:%M:%S")
                
                # Actualizar velas para precio de cierre real
                fresh_candles = self.iq.get_candles(self.active_pair, 60, 5)
                close_price = fresh_candles[-1]['close'] if fresh_candles else self.current_tick_price
                entry_price = self.current_trade["entry_price"]
                
                if result == "WIN":
                    self.session_stats["wins"] += 1
                    self.session_stats["net_profit"] += profit
                    # Reset Martingala
                    self.current_amount = self.base_amount
                    self.current_martingale_step = 0
                elif result == "LOSS":
                    self.session_stats["losses"] += 1
                    lost_amount = self.current_trade["amount"]
                    self.session_stats["net_profit"] -= lost_amount
                    profit = -lost_amount
                    
                    # Aplicar Martingala si está habilitada
                    if self.current_martingale_step < self.martingale_steps:
                        self.current_martingale_step += 1
                        self.current_amount = round(self.current_amount * self.martingale_multiplier, 2)
                        logger.info(f"Martingala paso {self.current_martingale_step}: Próximo monto = ${self.current_amount}")
                    else:
                        self.current_amount = self.base_amount
                        self.current_martingale_step = 0
                else:
                    self.session_stats["equals"] += 1

                self.session_stats["total_trades"] += 1
                total = self.session_stats["wins"] + self.session_stats["losses"]
                if total > 0:
                    self.session_stats["winrate"] = round((self.session_stats["wins"] / total) * 100, 1)

                trade_record = {
                    "id": order_id,
                    "pair": self.active_pair,
                    "direction": trade_dir,
                    "result": result,
                    "profit": round(profit, 2),
                    "entry_time": self.current_trade["entry_time"],
                    "close_time": close_time_str,
                    "entry_price": entry_price,
                    "close_price": close_price,
                    "amount": self.current_trade["amount"],
                    "martingale_step": self.current_martingale_step
                }
                self.trade_history.append(trade_record)
                
                # Notificación final por Telegram
                self.telegram.notify_result(
                    pair=self.active_pair,
                    direction=trade_dir,
                    result=result,
                    entry_time=self.current_trade["entry_time"],
                    close_time=close_time_str,
                    entry_price=entry_price,
                    close_price=close_price,
                    profit=profit,
                    stats=self.session_stats
                )
                
                logger.info(f"Operación finalizada: {result} ({profit:.2f}$). Saldo sesión: {self.session_stats['net_profit']:.2f}$")
                
                # Limpiar y volver a buscar
                self.state = "SEARCHING"
                self.pending_signal = None
                self.current_trade = None

    def update_config(self, pair: str, timeframe: int, amount: float, martingale: int, account_type: str):
        """Actualiza parámetros desde el panel de control web."""
        self.active_pair = pair.upper()
        self.timeframe = int(timeframe)
        self.base_amount = float(amount)
        if self.current_martingale_step == 0:
            self.current_amount = self.base_amount
        self.martingale_steps = int(martingale)
        if account_type.upper() != self.iq.account_type:
            self.iq.change_balance(account_type.upper())
        logger.info(f"Configuración actualizada: Par={self.active_pair}, TF={self.timeframe}s, Monto=${self.base_amount}, Martingala={self.martingale_steps}, Cuenta={self.iq.account_type}")
