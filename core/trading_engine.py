"""
Motor Principal de Trading y Monitoreo Multi-Par en Simultáneo Segundo a Segundo
Implementa la máquina de estados con análisis concurrente de hasta 20 pares:
- 10 Pares Mercado Normal: EURUSD, GBPUSD, USDJPY, EURJPY, AUDUSD, USDCAD, USDCHF, EURGBP, NZDUSD, GBPJPY
- 10 Pares Mercado OTC: EURUSD-OTC, GBPUSD-OTC, USDJPY-OTC, EURJPY-OTC, AUDUSD-OTC, USDCAD-OTC, USDCHF-OTC, NZDUSD-OTC, EURGBP-OTC, GBPJPY-OTC

REGLA ESTRICTA DE OPERACIÓN SECUENCIAL:
- El bot analiza todos los pares seleccionados en simultáneo.
- En cuanto UN par genera señal, entra en CONFIRMING y luego IN_TRADE.
- DURANTE CONFIRMING E IN_TRADE: Las demás señales se bloquean estrictamente (una señal a la vez).
- Solo cuando la operación finaliza y se verifica el resultado (WIN/LOSS), el bot vuelve a analizar todos los pares.
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
        
        # MÁQUINA DE ESTADOS GLOBAL SECUENCIAL (UNA SEÑAL A LA VEZ)
        # Estados: 'SEARCHING', 'CONFIRMING', 'IN_TRADE'
        self.engine_mode = "SEARCHING"
        self.locked_pair: Optional[str] = None
        self.pending_signal: Optional[Dict[str, Any]] = None
        self.current_trade: Optional[Dict[str, Any]] = None
        
        # Estados de pares para la cuadrícula
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
                    "tick_price": 0.0,
                    "last_analyzed_time": 0,
                    "status_msg": "Buscando señal VIP...",
                    "seconds_left": 0
                }
        current_set = set(p.upper() for p in self.selected_pairs)
        to_del = [k for k in self.pairs_state if k not in current_set]
        for k in to_del:
            del self.pairs_state[k]

    def set_selected_pairs(self, pairs: List[str]) -> Tuple[bool, str]:
        valid_pairs = [p.strip().upper() for p in pairs if p.strip()]
        if not valid_pairs:
            return False, "Debes seleccionar al menos un par de divisas."
        
        self.selected_pairs = valid_pairs
        if self.active_pair not in self.selected_pairs:
            self.active_pair = self.selected_pairs[0]
        
        self._init_pair_states()
        if self.is_running:
            self.iq.start_streams(self.selected_pairs, self.timeframe)
        logger.info(f"Pares actualizados para análisis simultáneo ({len(self.selected_pairs)}): {self.selected_pairs}")
        return True, f"Se han seleccionado {len(self.selected_pairs)} pares para análisis en simultáneo."

    def set_active_pair(self, pair: str):
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
        self.engine_mode = "SEARCHING"
        self.locked_pair = None
        self.pending_signal = None
        self.current_trade = None
        self.current_amount = self.base_amount
        self.current_martingale_step = 0
        self._init_pair_states()
        
        self.iq.start_streams(self.selected_pairs, self.timeframe)
        
        pairs_count = len(self.selected_pairs)
        self.current_status_message = f"Bot iniciado - Monitoreando {pairs_count} pares en simultáneo (Una señal a la vez)..."
        
        balance = self.iq.get_balance()
        pairs_str = ", ".join(self.selected_pairs[:6]) + (f" (+{pairs_count - 6} más)" if pairs_count > 6 else "")
        self.telegram.notify_bot_status(True, pairs_str, self.iq.account_type, balance)
        logger.info(f"Bot iniciado con {pairs_count} pares en simultáneo (Modo Secuencial 1 a la vez): {self.selected_pairs}")
        return True, f"Bot encendido exitosamente con {pairs_count} pares en escaneo activo."

    def stop(self) -> Tuple[bool, str]:
        if not self.is_running:
            return True, "El bot ya está detenido."
        
        self.is_running = False
        self.iq.stop_streams(self.timeframe)
        self.engine_mode = "SEARCHING"
        self.locked_pair = None
        self.pending_signal = None
        self.current_trade = None

        for p, st in self.pairs_state.items():
            st["state"] = "SEARCHING"
            st["status_msg"] = "Bot detenido"
        
        self.current_status_message = "Bot detenido por el usuario."
        balance = self.iq.get_balance()
        self.telegram.notify_bot_status(False, f"{len(self.selected_pairs)} pares", self.iq.account_type, balance)
        logger.info("Bot detenido.")
        return True, "Bot apagado correctamente."

    async def broadcast_tick(self, now: float):
        """Transmite ticks instantáneos de alta frecuencia (sub-segundo/milisegundo)."""
        if not self.websocket_listeners:
            return
        
        dt = datetime.fromtimestamp(now)
        time_ms_str = dt.strftime("%H:%M:%S.%f")[:-3]
        
        prices_map = {}
        for p in self.selected_pairs:
            st = self.pairs_state.get(p)
            if st:
                prices_map[p] = st.get("tick_price", 0.0)

        data = {
            "type": "tick",
            "ts": now,
            "time_ms": time_ms_str,
            "pair": self.active_pair,
            "tick_price": self.current_tick_price,
            "seconds_left": self.seconds_left_in_candle,
            "engine_mode": self.engine_mode,
            "locked_pair": self.locked_pair,
            "prices": prices_map
        }
        dead_clients = set()
        for ws in self.websocket_listeners:
            try:
                await ws.send_json(data)
            except Exception:
                dead_clients.add(ws)
        self.websocket_listeners.difference_update(dead_clients)

    async def broadcast_status(self):
        """Envía el estado completo consolidado a los clientes conectados por WebSocket."""
        pairs_overview = []
        for p in self.selected_pairs:
            st = self.pairs_state.get(p, {})
            # Estado visible del par en la cuadrícula
            if self.engine_mode != "SEARCHING" and self.locked_pair == p:
                card_state = self.engine_mode
                card_msg = "Confirmando vela..." if self.engine_mode == "CONFIRMING" else "Operación en curso..."
            elif self.engine_mode != "SEARCHING" and self.locked_pair != p:
                card_state = "PAUSED"
                card_msg = f"Pausado ({self.locked_pair} activo)"
            else:
                card_state = "SEARCHING"
                card_msg = st.get("status_msg", "Buscando...")

            pairs_overview.append({
                "pair": p,
                "state": card_state,
                "tick_price": st.get("tick_price", 0.0),
                "status_msg": card_msg,
                "signal": self.pending_signal.get("direction") if (self.locked_pair == p and self.pending_signal) else None,
                "is_active": (p == self.active_pair)
            })

        data = {
            "type": "full",
            "is_running": self.is_running,
            "engine_mode": self.engine_mode,
            "state": self.engine_mode, # Para compatibilidad con radar existente
            "pair": self.active_pair,
            "locked_pair": self.locked_pair,
            "selected_pairs": self.selected_pairs,
            "pairs_overview": pairs_overview,
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
            "history": self.trade_history[-20:]
        }
        
        dead_clients = set()
        for ws in self.websocket_listeners:
            try:
                await ws.send_json(data)
            except Exception:
                dead_clients.add(ws)
        self.websocket_listeners.difference_update(dead_clients)

    async def run_loop(self):
        """Bucle infinito asíncrono con streaming instantáneo de alta frecuencia (50ms)."""
        logger.info("Iniciando bucle de control secuencial de alta frecuencia...")
        last_strategy_second = -1
        last_tick_broadcast_time = 0.0

        while True:
            try:
                now = time.time()
                current_int_sec = int(now)

                # =========================================================
                # 1. STREAMING DE ALTA FRECUENCIA (CADA 50-70 MS)
                # =========================================================
                if self.is_running and self.selected_pairs:
                    for pair in self.selected_pairs:
                        p_state = self.pairs_state.setdefault(pair, {
                            "pair": pair,
                            "state": "SEARCHING",
                            "tick_price": 0.0,
                            "last_analyzed_time": 0,
                            "status_msg": "Analizando...",
                            "seconds_left": self.seconds_left_in_candle
                        })
                        p_state["tick_price"] = self.iq.get_realtime_price(pair, self.timeframe)
                        if pair == self.active_pair:
                            self.current_tick_price = p_state["tick_price"]

                    self.seconds_left_in_candle = self.timeframe - (current_int_sec % self.timeframe)
                    if self.seconds_left_in_candle == self.timeframe:
                        self.seconds_left_in_candle = 0

                    if (now - last_tick_broadcast_time) >= 0.06:
                        await self.broadcast_tick(now)
                        last_tick_broadcast_time = now

                # =========================================================
                # 2. EVALUACIÓN DE ESTRATEGIA SECUENCIAL (CADA SEGUNDO)
                # =========================================================
                if current_int_sec != last_strategy_second:
                    last_strategy_second = current_int_sec
                    if self.is_running and self.selected_pairs:
                        await self._tick_sequential_strategy()
                    else:
                        self.seconds_left_in_candle = 0
                        self.current_status_message = "Bot detenido - Esperando activación en el panel admin"

                    await self.broadcast_status()

            except Exception as e:
                logger.error(f"Error en bucle de TradingEngine: {e}", exc_info=True)
            
            await asyncio.sleep(0.05)

    async def _tick_sequential_strategy(self):
        """
        Lógica Secuencial Estricta:
        1. SEARCHING: Escanea todos los pares simultáneamente. Si uno da señal, se bloquea exclusivamente ese par.
        2. CONFIRMING: Monitorea ÚNICAMENTE el par bloqueado hasta que cierre su vela.
        3. IN_TRADE: Monitorea ÚNICAMENTE la operación abierta del par hasta la expiración.
        4. RESULT: Procesa resultado. Solo tras cerrarse la operación, desbloquea y vuelve a analizar.
        """
        server_ts = self.iq.get_server_timestamp()
        dt_server = datetime.fromtimestamp(server_ts)
        time_str = dt_server.strftime("%H:%M:%S")

        # =========================================================
        # FASE 1: SEARCHING (Todos los pares se analizan hasta que APARECE UNA SEÑAL)
        # =========================================================
        if self.engine_mode == "SEARCHING":
            self.current_status_message = f"[{time_str}] Escaneando {len(self.selected_pairs)} pares en simultáneo ({self.seconds_left_in_candle}s restantes)"
            current_minute_slot = current_int_sec // self.timeframe

            for pair in self.selected_pairs:
                p_state = self.pairs_state.get(pair)
                if not p_state:
                    continue

                # Evitar consultas redundantes de velas en el mismo minuto si ya fue analizado
                if p_state.get("analyzed_minute_slot") == current_minute_slot:
                    continue

                candles = await asyncio.to_thread(self.iq.get_candles, pair, self.timeframe, 60)
                if not candles or len(candles) < 10:
                    continue

                closed_candle = candles[-2]
                closed_candle_time = closed_candle.get('from', 0)

                p_state["analyzed_minute_slot"] = current_minute_slot
                # Si la vela cerró recientemente
                if closed_candle_time != p_state["last_analyzed_time"]:
                    p_state["last_analyzed_time"] = closed_candle_time
                    analysis = self.indicator.analyze_candles(candles[:-1])

                    if analysis.get('signal'):
                        direction = analysis['signal']
                        candle_dt_str = datetime.fromtimestamp(closed_candle_time).strftime("%H:%M:%S")

                        # ¡BLOQUEAR MOTOR EN ESTE PAR! (Una señal a la vez)
                        self.locked_pair = pair
                        self.active_pair = pair
                        self.engine_mode = "CONFIRMING"
                        
                        self.pending_signal = {
                            "pair": pair,
                            "direction": direction,
                            "detected_at": time_str,
                            "candle_time": candle_dt_str,
                            "signal_candle_from": closed_candle_time,
                            "confirm_candle_from": candles[-1].get('from', 0)
                        }

                        tf_label = "1M" if self.timeframe == 60 else f"{self.timeframe//60}M"
                        self.current_status_message = f"¡SEÑAL {direction} EN {pair}! Esperando confirmación (Otros pares en pausa)..."
                        logger.info(f"Señal VIP detectada: {pair} {direction}. Bloqueando escaneo en {pair} hasta resultado.")
                        
                        self.telegram.notify_pre_signal(pair, direction, tf_label, candle_dt_str)
                        # Salir inmediatamente del bucle: NO permitir ninguna otra señal
                        break

        # =========================================================
        # FASE 2: CONFIRMING (Exclusivo para el par bloqueado)
        # =========================================================
        elif self.engine_mode == "CONFIRMING":
            pair = self.locked_pair
            direction = self.pending_signal["direction"]
            self.current_status_message = (
                f"[{time_str}] CONFIRMANDO SEÑAL {direction} EN {pair}: "
                f"Quedan {self.seconds_left_in_candle}s para evaluar la vela."
            )

            # En el último segundo de la vela (<= 1s para segundo 00)
            if self.seconds_left_in_candle <= 1:
                candles = await asyncio.to_thread(self.iq.get_candles, pair, self.timeframe, 10)
                if candles and len(candles) >= 2:
                    confirm_candle = candles[-1]
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
                        entry_time_str = datetime.fromtimestamp(server_ts + 1).strftime("%H:%M:%S")
                        trade_amount = self.current_amount

                        logger.info(f"¡Vela confirmada! Ejecutando {direction} en {pair} a las {entry_time_str}")
                        ok, order_id, msg = await asyncio.to_thread(self.iq.buy_option, pair, trade_amount, direction, self.expiration)

                        if ok:
                            self.current_trade = {
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
                            self.engine_mode = "IN_TRADE"
                            self.current_status_message = f"OPERACIÓN EN CURSO: {pair} {direction} ${trade_amount} (Expiración 1M)"
                            
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
                            # Si falló la orden, desbloquear y volver a buscar
                            self.engine_mode = "SEARCHING"
                            self.locked_pair = None
                            self.pending_signal = None
                    else:
                        logger.info(f"Señal en {pair} no confirmada: {reason}. Reanudando escaneo general.")
                        self.telegram.notify_confirmation_failed(pair, direction, reason)
                        # No confirmada: desbloquear y volver a analizar todos los pares
                        self.engine_mode = "SEARCHING"
                        self.locked_pair = None
                        self.pending_signal = None

        # =========================================================
        # FASE 3: IN_TRADE (Exclusivo: espera hasta el cierre exacto)
        # =========================================================
        elif self.engine_mode == "IN_TRADE":
            pair = self.locked_pair
            cur_trade = self.current_trade
            remaining = cur_trade["end_ts"] - server_ts
            trade_dir = cur_trade["direction"]

            self.current_status_message = (
                f"[{time_str}] OPERACIÓN EN CURSO: {pair} {trade_dir} ${cur_trade['amount']} - "
                f"Cierre en: {max(0, remaining)}s"
            )

            if remaining <= 0:
                self.current_status_message = f"[{time_str}] Verificando resultado de {pair} con el broker..."
                await asyncio.sleep(1.5)

                order_id = cur_trade["id"]
                result, profit, _, _ = await asyncio.to_thread(self.iq.check_result, order_id)
                close_time_str = datetime.fromtimestamp(self.iq.get_server_timestamp()).strftime("%H:%M:%S")

                fresh_candles = await asyncio.to_thread(self.iq.get_candles, pair, 60, 5)
                close_price = fresh_candles[-1]['close'] if fresh_candles else self.current_tick_price
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

                # ¡SOLO AHORA SE DESBLOQUEA Y SE VUELVE A ANALIZAR TODOS LOS PARES!
                self.engine_mode = "SEARCHING"
                self.locked_pair = None
                self.pending_signal = None
                self.current_trade = None
                self.current_status_message = f"Operación finalizada ({result}). Reanudando análisis simultáneo de todos los pares..."

    def update_config(self, pairs: List[str], timeframe: int, amount: float, martingale: int, account_type: str):
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
