"""
Motor Principal de Trading y Monitoreo Multi-Par en Simultáneo Segundo a Segundo
Implementa la máquina de estados con análisis concurrente de hasta 20 pares:
- 10 Pares Mercado Normal: EURUSD, GBPUSD, USDJPY, EURJPY, AUDUSD, USDCAD, USDCHF, EURGBP, NZDUSD, GBPJPY
- 10 Pares Mercado OTC: EURUSD-OTC, GBPUSD-OTC, USDJPY-OTC, EURJPY-OTC, AUDUSD-OTC, USDCAD-OTC, USDCHF-OTC, NZDUSD-OTC, EURGBP-OTC, GBPJPY-OTC

Máquina de estados por cada par:
1. SEARCHING: Escaneo simultáneo de señales con SCRIPT VIP.
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
        
        # Pares seleccionados por el administrador
        self.selected_pairs: List[str] = list(self.config.TRADING_PAIRS) if self.config.TRADING_PAIRS else ["EURUSD", "GBPUSD", "USDJPY", "EURJPY"]
        self.active_pair: str = self.selected_pairs[0] if self.selected_pairs else "EURUSD"
        
        self.timeframe = self.config.TIMEFRAME
        self.expiration = self.config.EXPIRATION_TIME
        self.base_amount = self.config.TRADE_AMOUNT
        self.current_amount = self.config.TRADE_AMOUNT
        self.martingale_steps = self.config.MARTINGALE_STEPS
        self.martingale_multiplier = self.config.MARTINGALE_MULTIPLIER
        self.current_martingale_step = 0
        
        # Estados independientes por cada par seleccionado
        # key: 'EURUSD' -> {'state': 'SEARCHING', 'pending_signal': ..., 'current_trade': ..., 'tick_price': 1.08, ...}
        self.pairs_state: Dict[str, Dict[str, Any]] = {}
        self._init_pair_states()
        
        # Historial y Estadísticas globales de sesión
        self.trade_history: List[Dict[str, Any]] = []
        self.session_stats = {
            "wins": 0,
            "losses": 0,
            "equals": 0,
            "net_profit": 0.0,
            "total_trades": 0,
            "winrate": 0.0
        }
        
        # Streaming WebSocket a clientes web
        self.websocket_listeners = set()
        self.current_status_message = "Bot detenido"
        self.current_tick_price = 0.0
        self.seconds_left_in_candle = 0

    def _init_pair_states(self):
        """Inicializa o actualiza el estado de cada par seleccionado."""
        for p in self.selected_pairs:
            p_upper = p.upper()
            if p_upper not in self.pairs_state:
                self.pairs_state[p_upper] = {
                    "pair": p_upper,
                    "state": "SEARCHING",
                    "pending_signal": None,
                    "current_trade": None,
                    "tick_price": 0.0,
                    "last_analyzed_time": 0,
                    "status_msg": "Buscando señal VIP...",
                    "seconds_left": 0
                }
        # Eliminar pares deseleccionados
        current_set = set(p.upper() for p in self.selected_pairs)
        to_del = [k for k in self.pairs_state if k not in current_set]
        for k in to_del:
            del self.pairs_state[k]

    def set_selected_pairs(self, pairs: List[str]) -> Tuple[bool, str]:
        """Permite al administrador seleccionar los pares que desea analizar en simultáneo."""
        valid_pairs = [p.strip().upper() for p in pairs if p.strip()]
        if not valid_pairs:
            return False, "Debes seleccionar al menos un par de divisas."
        
        self.selected_pairs = valid_pairs
        if self.active_pair not in self.selected_pairs:
            self.active_pair = self.selected_pairs[0]
        
        self._init_pair_states()
        logger.info(f"Pares actualizados para análisis simultáneo ({len(self.selected_pairs)}): {self.selected_pairs}")
        return True, f"Se han seleccionado {len(self.selected_pairs)} pares para análisis en simultáneo."

    def set_active_pair(self, pair: str):
        """Cambia el par destacado visualmente en el radar principal."""
        pair_upper = pair.upper()
        if pair_upper in self.selected_pairs or pair_upper in self.pairs_state:
            self.active_pair = pair_upper
            if pair_upper in self.pairs_state:
                self.current_tick_price = self.pairs_state[pair_upper].get("tick_price", 0.0)

    def start(self) -> Tuple[bool, str]:
        if self.is_running:
            return True, "El bot ya está en ejecución."
        
        if not self.selected_pairs:
            return False, "Debes seleccionar al menos un par antes de encender el bot."

        success, msg = self.iq.connect()
        self.is_running = True
        self.current_amount = self.base_amount
        self.current_martingale_step = 0
        self._init_pair_states()
        
        pairs_count = len(self.selected_pairs)
        self.current_status_message = f"Bot iniciado - Monitoreando {pairs_count} pares en simultáneo..."
        
        balance = self.iq.get_balance()
        pairs_str = ", ".join(self.selected_pairs[:6]) + (f" (+{pairs_count - 6} más)" if pairs_count > 6 else "")
        self.telegram.notify_bot_status(True, pairs_str, self.iq.account_type, balance)
        logger.info(f"Bot iniciado con {pairs_count} pares en simultáneo: {self.selected_pairs}")
        return True, f"Bot encendido exitosamente con {pairs_count} pares en escaneo activo."

    def stop(self) -> Tuple[bool, str]:
        if not self.is_running:
            return True, "El bot ya está detenido."
        
        self.is_running = False
        for p, st in self.pairs_state.items():
            st["state"] = "SEARCHING"
            st["pending_signal"] = None
            st["status_msg"] = "Bot detenido"
        
        self.current_status_message = "Bot detenido por el usuario."
        balance = self.iq.get_balance()
        self.telegram.notify_bot_status(False, f"{len(self.selected_pairs)} pares", self.iq.account_type, balance)
        logger.info("Bot detenido.")
        return True, "Bot apagado correctamente."

    async def broadcast_status(self):
        """Envía el estado segundo a segundo a los clientes conectados por WebSocket."""
        # Estado del par actualmente destacado
        active_state_data = self.pairs_state.get(self.active_pair, {})
        featured_state = active_state_data.get("state", "SEARCHING")
        featured_pending = active_state_data.get("pending_signal", None)
        featured_trade = active_state_data.get("current_trade", None)
        featured_price = active_state_data.get("tick_price", self.current_tick_price)

        # Si el par destacado está en SEARCHING pero otro par está en CONFIRMING o IN_TRADE,
        # lo destacamos dinámicamente para que el usuario vea la acción
        for p, st in self.pairs_state.items():
            if st.get("state") in ["IN_TRADE", "CONFIRMING"]:
                featured_state = st.get("state")
                featured_pending = st.get("pending_signal")
                featured_trade = st.get("current_trade")
                self.active_pair = p
                featured_price = st.get("tick_price", 0.0)
                break

        # Resumen ligero de cada par para la cuadrícula Multi-Par
        pairs_overview = []
        for p in self.selected_pairs:
            st = self.pairs_state.get(p, {})
            pairs_overview.append({
                "pair": p,
                "state": st.get("state", "SEARCHING"),
                "tick_price": st.get("tick_price", 0.0),
                "status_msg": st.get("status_msg", "Buscando..."),
                "signal": st.get("pending_signal", {}).get("direction") if st.get("pending_signal") else None,
                "is_active": (p == self.active_pair)
            })

        data = {
            "is_running": self.is_running,
            "state": featured_state,
            "pair": self.active_pair,
            "selected_pairs": self.selected_pairs,
            "pairs_overview": pairs_overview,
            "timeframe": self.timeframe,
            "seconds_left": self.seconds_left_in_candle,
            "tick_price": featured_price,
            "status_message": self.current_status_message,
            "balance": self.iq.get_balance(),
            "account_type": self.iq.account_type,
            "is_simulation": self.iq.is_simulation,
            "pending_signal": featured_pending,
            "current_trade": featured_trade,
            "stats": self.session_stats,
            "history": self.trade_history[-20:] # Últimas 20 operaciones
        }
        
        dead_clients = set()
        for ws in self.websocket_listeners:
            try:
                await ws.send_json(data)
            except Exception:
                dead_clients.add(ws)
        self.websocket_listeners.difference_update(dead_clients)

    async def run_loop(self):
        """Bucle infinito asíncrono con control segundo a segundo multi-par."""
        logger.info("Iniciando bucle de control segundo a segundo multi-par...")
        while True:
            try:
                if self.is_running and self.selected_pairs:
                    await self._tick()
                else:
                    self.seconds_left_in_candle = 0
                    self.current_status_message = "Bot detenido - Esperando activación en el panel admin"
                
                await self.broadcast_status()
            except Exception as e:
                logger.error(f"Error en tick multi-par de TradingEngine: {e}", exc_info=True)
            
            await asyncio.sleep(1.0)

    async def _tick(self):
        server_ts = self.iq.get_server_timestamp()
        dt_server = datetime.fromtimestamp(server_ts)
        time_str = dt_server.strftime("%H:%M:%S")
        
        # Segundos restantes para que cierre la vela actual del timeframe configurado
        self.seconds_left_in_candle = self.timeframe - (server_ts % self.timeframe)
        if self.seconds_left_in_candle == self.timeframe:
            self.seconds_left_in_candle = 0

        total_pairs = len(self.selected_pairs)
        active_confirming = 0
        active_trades = 0

        # Iteramos cada par seleccionado para análisis simultáneo
        for pair in self.selected_pairs:
            p_state = self.pairs_state.setdefault(pair, {
                "pair": pair,
                "state": "SEARCHING",
                "pending_signal": None,
                "current_trade": None,
                "tick_price": 0.0,
                "last_analyzed_time": 0,
                "status_msg": "Analizando...",
                "seconds_left": self.seconds_left_in_candle
            })
            p_state["seconds_left"] = self.seconds_left_in_candle

            # Obtener velas del par (60 velas)
            candles = self.iq.get_candles(pair, self.timeframe, 60)
            if not candles or len(candles) < 10:
                continue

            latest_candle = candles[-1]
            p_state["tick_price"] = float(latest_candle.get('close', 0.0))
            if pair == self.active_pair:
                self.current_tick_price = p_state["tick_price"]

            # =========================================================
            # ESTADO 1: SEARCHING (Buscando señal SCRIPT VIP en este par)
            # =========================================================
            if p_state["state"] == "SEARCHING":
                p_state["status_msg"] = f"Buscando señal ({self.seconds_left_in_candle}s)"
                
                closed_candle = candles[-2]
                closed_candle_time = closed_candle.get('from', 0)
                
                if closed_candle_time != p_state["last_analyzed_time"]:
                    p_state["last_analyzed_time"] = closed_candle_time
                    analysis = self.indicator.analyze_candles(candles[:-1])
                    
                    if analysis.get('signal'):
                        direction = analysis['signal']  # 'CALL' o 'PUT'
                        candle_dt_str = datetime.fromtimestamp(closed_candle_time).strftime("%H:%M:%S")
                        
                        p_state["pending_signal"] = {
                            "pair": pair,
                            "direction": direction,
                            "detected_at": time_str,
                            "candle_time": candle_dt_str,
                            "signal_candle_from": closed_candle_time,
                            "confirm_candle_from": latest_candle.get('from', 0)
                        }
                        p_state["state"] = "CONFIRMING"
                        p_state["status_msg"] = f"¡SEÑAL {direction}! Confirmando..."
                        
                        # Destacar este par en pantalla
                        self.active_pair = pair
                        tf_label = "1M" if self.timeframe == 60 else f"{self.timeframe//60}M"
                        logger.info(f"Señal VIP detectada: {pair} {direction}. Esperando confirmación.")
                        self.telegram.notify_pre_signal(pair, direction, tf_label, candle_dt_str)

            # =========================================================
            # ESTADO 2: CONFIRMING (Esperando vela a favor en este par)
            # =========================================================
            elif p_state["state"] == "CONFIRMING":
                active_confirming += 1
                direction = p_state["pending_signal"]["direction"]
                p_state["status_msg"] = f"Confirmando {direction} ({self.seconds_left_in_candle}s)"
                
                # En el segundo final de la vela (<= 1s para el segundo 00)
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
                        # Confirmada: Entramos en el segundo exacto 00 de la siguiente vela
                        entry_time_str = datetime.fromtimestamp(server_ts + 1).strftime("%H:%M:%S")
                        trade_amount = self.current_amount
                        
                        logger.info(f"¡Vela confirmada! Ejecutando {direction} en {pair} a las {entry_time_str}")
                        ok, order_id, msg = self.iq.buy_option(pair, trade_amount, direction, self.expiration)
                        
                        if ok:
                            p_state["current_trade"] = {
                                "id": order_id,
                                "pair": pair,
                                "direction": direction,
                                "entry_time": entry_time_str,
                                "entry_price": c_close,
                                "amount": trade_amount,
                                "expiration": self.expiration,
                                "start_ts": server_ts,
                                "end_ts": server_ts + (self.expiration * 60)
                            }
                            p_state["state"] = "IN_TRADE"
                            p_state["status_msg"] = f"Operación {direction} en curso..."
                            self.active_pair = pair
                            
                            self.telegram.notify_entry(
                                pair=pair,
                                direction=direction,
                                entry_time=entry_time_str,
                                entry_price=c_close,
                                expiration=self.expiration,
                                amount=trade_amount
                            )
                        else:
                            logger.error(f"Error al enviar orden en {pair}: {msg}")
                            p_state["status_msg"] = f"Error orden: {msg}"
                            p_state["state"] = "SEARCHING"
                            p_state["pending_signal"] = None
                    else:
                        logger.info(f"Señal en {pair} no confirmada: {reason}")
                        self.telegram.notify_confirmation_failed(pair, direction, reason)
                        p_state["state"] = "SEARCHING"
                        p_state["pending_signal"] = None

            # =========================================================
            # ESTADO 3: IN_TRADE (Operación abierta a 1 minuto en este par)
            # =========================================================
            elif p_state["state"] == "IN_TRADE":
                active_trades += 1
                cur_trade = p_state["current_trade"]
                remaining = cur_trade["end_ts"] - server_ts
                trade_dir = cur_trade["direction"]
                p_state["status_msg"] = f"Operación {trade_dir} ({max(0, remaining)}s)"
                
                if remaining <= 0:
                    p_state["status_msg"] = "Verificando resultado con broker..."
                    await asyncio.sleep(1.5)
                    
                    order_id = cur_trade["id"]
                    result, profit, _, _ = self.iq.check_result(order_id)
                    close_time_str = datetime.fromtimestamp(self.iq.get_server_timestamp()).strftime("%H:%M:%S")
                    
                    fresh_candles = self.iq.get_candles(pair, 60, 5)
                    close_price = fresh_candles[-1]['close'] if fresh_candles else p_state["tick_price"]
                    entry_price = cur_trade["entry_price"]
                    
                    if result == "WIN":
                        self.session_stats["wins"] += 1
                        self.session_stats["net_profit"] += profit
                        self.current_amount = self.base_amount
                        self.current_martingale_step = 0
                    elif result == "LOSS":
                        self.session_stats["losses"] += 1
                        lost_amount = cur_trade["amount"]
                        self.session_stats["net_profit"] -= lost_amount
                        profit = -lost_amount
                        
                        if self.current_martingale_step < self.martingale_steps:
                            self.current_martingale_step += 1
                            self.current_amount = round(self.current_amount * self.martingale_multiplier, 2)
                        else:
                            self.current_amount = self.base_amount
                            self.current_martingale_step = 0
                    else:
                        self.session_stats["equals"] += 1

                    self.session_stats["total_trades"] += 1
                    tot = self.session_stats["wins"] + self.session_stats["losses"]
                    if tot > 0:
                        self.session_stats["winrate"] = round((self.session_stats["wins"] / tot) * 100, 1)

                    trade_record = {
                        "id": order_id,
                        "pair": pair,
                        "direction": trade_dir,
                        "result": result,
                        "profit": round(profit, 2),
                        "entry_time": cur_trade["entry_time"],
                        "close_time": close_time_str,
                        "entry_price": entry_price,
                        "close_price": close_price,
                        "amount": cur_trade["amount"],
                        "martingale_step": self.current_martingale_step
                    }
                    self.trade_history.append(trade_record)
                    
                    self.telegram.notify_result(
                        pair=pair,
                        direction=trade_dir,
                        result=result,
                        entry_time=cur_trade["entry_time"],
                        close_time=close_time_str,
                        entry_price=entry_price,
                        close_price=close_price,
                        profit=profit,
                        stats=self.session_stats
                    )
                    
                    logger.info(f"Operación finalizada {pair}: {result} (${profit:.2f}). Saldo neto: ${self.session_stats['net_profit']:.2f}")
                    p_state["state"] = "SEARCHING"
                    p_state["pending_signal"] = None
                    p_state["current_trade"] = None

        # Mensaje global de estado para el banner principal
        if active_trades > 0:
            self.current_status_message = f"[{time_str}] {active_trades} operación(es) en curso | Monitoreando {total_pairs} pares."
        elif active_confirming > 0:
            self.current_status_message = f"[{time_str}] Confirmando {active_confirming} señal(es) VIP | Monitoreando {total_pairs} pares."
        else:
            self.current_status_message = f"[{time_str}] Escaneando {total_pairs} pares en simultáneo ({self.timeframe}s) - Vela: {self.seconds_left_in_candle}s restantes"

    def update_config(self, pairs: List[str], timeframe: int, amount: float, martingale: int, account_type: str):
        """Actualiza parámetros desde el panel de control web."""
        if pairs:
            self.set_selected_pairs(pairs)
        self.timeframe = int(timeframe)
        self.base_amount = float(amount)
        if self.current_martingale_step == 0:
            self.current_amount = self.base_amount
        self.martingale_steps = int(martingale)
        if account_type.upper() != self.iq.account_type:
            self.iq.change_balance(account_type.upper())
        logger.info(f"Configuración actualizada: Pares={len(self.selected_pairs)}, TF={self.timeframe}s, Monto=${self.base_amount}, Martingala={self.martingale_steps}, Cuenta={self.iq.account_type}")
