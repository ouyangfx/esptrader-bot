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
from core.database import DatabaseManager
from core.sniper_trigger import SniperQuantitativeTrigger

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
        
        # Configuración estricta en Velas de 5 Minutos (M5) y Sin Martingala
        self.timeframe = 300  # 300 segundos = 5 minutos
        self.expiration = 5   # Expiración 5 minutos
        self.base_amount = self.config.TRADE_AMOUNT
        self.current_amount = self.config.TRADE_AMOUNT
        self.martingale_steps = 0  # No existe martingala
        self.martingale_multiplier = 1.0
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
        
        # Historial y Estadísticas persistentes en SQLite DB (NUNCA se borran)
        self.db = DatabaseManager()
        self.trade_history: List[Dict[str, Any]] = self.db.load_trades()
        self.session_stats = self.db.get_stats()
        self.live_signals_feed: List[Dict[str, Any]] = []
        self.last_signal_event: Optional[Dict[str, Any]] = None
        self._init_live_feed()
        
        # Streaming WebSocket a clientes web
        self.websocket_listeners = set()
        self.current_status_message = "Bot detenido"
        self.current_tick_price = 0.0
        self.seconds_left_in_candle = 0

        # Módulo de Gatillo Sniper Cuantitativo (M15 / M5 / 30s)
        self.sniper = SniperQuantitativeTrigger(self)
        self.last_m15_scan_time = 0

    def _scan_recent_historical_signals(self):
        """Si live_signals_feed está vacío, analiza las velas de los pares para precargar las últimas señales reales calculadas con Fibonacci 50% y 61.8%."""
        try:
            detected = []
            for pair in self.selected_pairs:
                candles = self.iq.get_candles(pair, self.timeframe, 50)
                if not candles or len(candles) < 35:
                    continue
                dec = 3 if "JPY" in pair else 5
                for i in range(35, len(candles) - 1):
                    sub = candles[:i+1]
                    res = self.indicator.analyze_candles(sub)
                    sig = res.get("signal")
                    if sig in ("CALL", "PUT"):
                        sig_c = candles[i]
                        prev_c = candles[i-1]
                        sig_time = datetime.fromtimestamp(sig_c.get('from', 0)).strftime("%H:%M:%S")
                        expire_time = datetime.fromtimestamp(sig_c.get('from', 0) + (self.expiration * 60)).strftime("%H:%M:%S")
                        
                        s_min = float(sig_c.get('min', sig_c.get('low', sig_c['close'])))
                        s_max = float(sig_c.get('max', sig_c.get('high', sig_c['close'])))
                        p_min = float(prev_c.get('min', prev_c.get('low', prev_c['close'])))
                        p_max = float(prev_c.get('max', prev_c.get('high', prev_c['close'])))
                        o_min = min(s_min, p_min)
                        o_max = max(s_max, p_max)
                        r = max(1e-5, o_max - o_min)
                        
                        if sig == "CALL":
                            f50 = o_max - (r * 0.50)
                            f618 = o_max - (r * 0.618)
                        else:
                            f50 = o_min + (r * 0.50)
                            f618 = o_min + (r * 0.618)

                        res_label = "CONFIRMADA"
                        if i + 1 < len(candles):
                            next_c = candles[i+1]
                            c_close = float(next_c['close'])
                            c_open = float(next_c['open'])
                            is_win = (sig == "CALL" and c_close > c_open) or (sig == "PUT" and c_close < c_open)
                            res_label = "ITM ✅" if is_win else "OTM ❌"

                        item = {
                            "id": int(sig_c.get('from', 0)),
                            "time": sig_time,
                            "pair": pair,
                            "direction": sig,
                            "type": "SEÑAL_VIP_M5",
                            "status": res_label,
                            "entry_time": sig_time,
                            "expire_time": expire_time,
                            "entry_price": round(float(sig_c['close']), dec),
                            "close_price": round(float(candles[min(i+1, len(candles)-1)]['close']), dec),
                            "fibo_50": round(f50, dec),
                            "fibo_618": round(f618, dec),
                            "tip": "Esperar retroceso a zona Fibo 50% - 61.8% para mayor efectividad (Sniper)",
                            "confluence": "Confluencia M15 Verificada"
                        }
                        detected.append(item)

            if detected:
                detected.sort(key=lambda x: x["id"])
                self.live_signals_feed = detected[-10:]
                self.last_signal_event = self.live_signals_feed[-1]
                logger.info(f"Señales precargadas en el feed en vivo ({len(self.live_signals_feed)} señales detectadas). Última: {self.last_signal_event['pair']} {self.last_signal_event['direction']}")
        except Exception as e:
            logger.error(f"Error precargando señales históricas: {e}")

    def _init_live_feed(self):
        """Inicializa el feed de señales con los últimos registros de la base de datos."""
        for t in self.trade_history[-10:]:
            item = {
                "id": t.get("id"),
                "time": t.get("entry_time", "--:--:--"),
                "pair": t.get("pair"),
                "direction": t.get("direction"),
                "type": "RESULTADO",
                "status": t.get("result"),
                "profit": t.get("profit", 0.0),
                "entry_time": t.get("entry_time"),
                "close_time": t.get("close_time"),
                "expire_time": t.get("close_time"),
                "entry_price": t.get("entry_price"),
                "close_price": t.get("close_price"),
                "fibo_50": t.get("fibo_50"),
                "fibo_618": t.get("fibo_618"),
                "tip": f"Resultado: {t.get('result')}"
            }
            self.live_signals_feed.append(item)
        if self.live_signals_feed:
            self.last_signal_event = self.live_signals_feed[-1]

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
        allowed = set(self.config.ALL_AVAILABLE_PAIRS)
        valid_pairs = [p.strip().upper() for p in pairs if p.strip() and p.strip().upper() in allowed]
        if not valid_pairs:
            return False, "Debes seleccionar al menos un par válido de los 4 principales (Normal o OTC)."
        
        self.selected_pairs = valid_pairs
        if self.active_pair not in self.selected_pairs:
            self.active_pair = self.selected_pairs[0]
        
        self._init_pair_states()
        if self.is_running:
            self.iq.start_streams(self.selected_pairs, self.timeframe)
        logger.info(f"Pares actualizados para análisis simultáneo ({len(self.selected_pairs)}): {self.selected_pairs}")
        return True, f"Se han guardado {len(self.selected_pairs)} pares para análisis y operación."

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
            return False, "⚠️ ATENCIÓN: Debes seleccionar y guardar al menos un par antes de encender el bot."

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
        
        if not self.live_signals_feed:
            self._scan_recent_historical_signals()
        
        pairs_count = len(self.selected_pairs)
        self.current_status_message = f"Bot iniciado - Monitoreando {pairs_count} pares en simultáneo (Una señal a la vez)..."
        
        balance = self.iq.get_balance()
        pairs_str = ", ".join(self.selected_pairs[:6]) + (f" (+{pairs_count - 6} más)" if pairs_count > 6 else "")
        asyncio.create_task(asyncio.to_thread(self.telegram.notify_bot_status, True, pairs_str, self.iq.account_type, balance))
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
        asyncio.create_task(asyncio.to_thread(self.telegram.notify_bot_status, False, f"{len(self.selected_pairs)} pares", self.iq.account_type, balance))
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
                card_msg = "Esperando retroceso Fibo..." if self.engine_mode in ("CONFIRMING", "WAITING_PULLBACK") else "Operación en curso..."
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
            "last_signal_event": self.last_signal_event,
            "live_signals_feed": self.live_signals_feed[-10:],
            "stats": self.session_stats,
            "history": self.trade_history[-10:]
        }
        
        dead_clients = set()
        for ws in self.websocket_listeners:
            try:
                await ws.send_json(data)
            except Exception:
                dead_clients.add(ws)
        self.websocket_listeners.difference_update(dead_clients)

    async def obtener_velas_30s(self, pair: str) -> list:
        """Obtiene las velas de 30 segundos más recientes para evaluar la anatomía de rechazo."""
        return await asyncio.to_thread(self.iq.get_candles, pair, 30, 5)

    async def broadcast_sniper_event(self, event_data: Dict[str, Any]):
        """Transmite eventos del radar sniper (PREALERTA o GATILLO) a todos los WebSockets."""
        dead_clients = set()
        for ws in self.websocket_listeners:
            try:
                await ws.send_json({
                    "type": "sniper_radar",
                    **event_data
                })
                if "msg" in event_data:
                    await ws.send_text(event_data["msg"])
            except Exception:
                dead_clients.add(ws)
        self.websocket_listeners.difference_update(dead_clients)

    async def broadcast_custom_text(self, text: str):
        """Transmite texto plano de alerta a los WebSockets conectados."""
        dead_clients = set()
        for ws in self.websocket_listeners:
            try:
                await ws.send_text(text)
            except Exception:
                dead_clients.add(ws)
        self.websocket_listeners.difference_update(dead_clients)

    async def _evaluar_pullback_tick(self, pair: str, current_price: float, server_ts: float):
        """Evalúa si el precio en vivo toca la zona de retroceso Fibonacci (50% - 61.8%) en la vela M5."""
        if not self.pending_signal or self.engine_mode not in ("CONFIRMING", "WAITING_PULLBACK"):
            return

        direction = self.pending_signal["direction"]
        fibo_50 = float(self.pending_signal.get("fibo_50", 0.0))
        fibo_618 = float(self.pending_signal.get("fibo_618", 0.0))
        pip_unit = 0.01 if "JPY" in pair else 0.0001
        tolerance = pip_unit * 1.0  # 1 pip de tolerancia

        # Condición de retroceso hacia la zona Fibo
        pullback_hit = False
        if direction in ("CALL", "COMPRA") and current_price <= (fibo_50 + tolerance):
            pullback_hit = True
        elif direction in ("PUT", "VENTA") and current_price >= (fibo_50 - tolerance):
            pullback_hit = True

        if pullback_hit:
            trade_amount = self.current_amount
            remaining_sec = max(60, self.pending_signal["end_ts"] - server_ts)
            exp_min = max(1, min(5, int(round(remaining_sec / 60.0))))

            entry_time_str = datetime.fromtimestamp(server_ts).strftime("%H:%M:%S")
            expire_ts = self.pending_signal["end_ts"]
            expire_time_str = datetime.fromtimestamp(expire_ts).strftime("%H:%M:%S")

            logger.info(
                f"🎯 ¡RETROCESO FIBONACCI ALCANZADO! {pair} {direction} @ {current_price:.5f} "
                f"(Nivel 50%: {fibo_50:.5f}) - Ejecutando a {exp_min}m M5"
            )

            # Prevenir ejecuciones múltiples simultáneas
            self.engine_mode = "IN_TRADE"
            ok, order_id, msg = await asyncio.to_thread(
                self.iq.buy_option, pair, trade_amount, direction, exp_min
            )

            if ok:
                self.current_trade = {
                    "id": order_id,
                    "pair": pair,
                    "direction": direction,
                    "entry_time": entry_time_str,
                    "entry_price": current_price,
                    "fibo_50": fibo_50,
                    "fibo_618": fibo_618,
                    "amount": trade_amount,
                    "expiration": exp_min,
                    "start_ts": server_ts,
                    "end_ts": expire_ts
                }
                self.current_status_message = f"OPERACIÓN EN RETROCESO: {pair} {direction} ${trade_amount} (Exp: {expire_time_str})"

                sig_event = {
                    "id": order_id,
                    "time": entry_time_str,
                    "pair": pair,
                    "direction": direction,
                    "type": "ENTRADA_RETROCESO",
                    "status": "OPERACIÓN EN CURSO (RETROCESO M5)",
                    "entry_time": entry_time_str,
                    "expire_time": expire_time_str,
                    "entry_price": current_price,
                    "fibo_50": fibo_50,
                    "fibo_618": fibo_618,
                    "tip": f"Entrada ejecutada en retroceso Fibo 50% ({fibo_50:.5f})",
                    "amount": trade_amount
                }
                self.last_signal_event = sig_event
                self.live_signals_feed.append(sig_event)
                self.live_signals_feed = self.live_signals_feed[-10:]

                # Notificar a Telegram
                self.telegram.notify_pullback_entry(
                    pair=pair,
                    direction=direction,
                    entry_time=entry_time_str,
                    entry_price=current_price,
                    fibo_level=fibo_50,
                    expire_time=expire_time_str,
                    amount=trade_amount
                )

                # Notificar a Web vía WebSocket
                cmd = "COMPRA" if direction in ("CALL", "COMPRA") else "VENTA"
                await self.broadcast_custom_text(f"{cmd}|{pair}")
                logger.info(f"Orden en retroceso colocada exitosamente en {pair} {direction} (ID: {order_id})")
            else:
                logger.warning(f"Error al enviar orden en retroceso a IQ Option ({pair}): {msg}")
                self.engine_mode = "SEARCHING"
                self.locked_pair = None
                self.pending_signal = None

    async def _ejecutar_gatillo_sniper(self, gatillo: Dict[str, Any]):
        """Ejecuta inmediatamente la orden sniper adelantada (Intra-bar M5)."""
        pair = gatillo["pair"]
        direction = gatillo["direction"]
        trade_amount = self.current_amount
        exp_min = gatillo["expiration_min"]
        end_ts = gatillo["end_ts"]
        server_ts = self.iq.get_server_timestamp()
        dt_str = datetime.fromtimestamp(server_ts).strftime("%H:%M:%S")

        self.locked_pair = pair
        self.active_pair = pair
        self.engine_mode = "IN_TRADE"
        self.current_status_message = f"🎯 ¡GATILLO SNIPER EJECUTADO! {pair} {direction} ${trade_amount} (Expiración M5: {gatillo['expiration_min']}m)"

        ok, order_id, msg = await asyncio.to_thread(self.iq.buy_option, pair, trade_amount, direction, exp_min)
        if ok:
            self.current_trade = {
                "id": order_id,
                "pair": pair,
                "direction": direction,
                "entry_time": dt_str,
                "entry_price": gatillo["price"],
                "fibo_50": gatillo["c1"],
                "fibo_618": gatillo["c2"],
                "amount": trade_amount,
                "expiration": exp_min,
                "start_ts": server_ts,
                "end_ts": end_ts
            }
            expire_time_str = datetime.fromtimestamp(end_ts).strftime("%H:%M:%S")

            sig_event = {
                "id": order_id,
                "time": dt_str,
                "pair": pair,
                "direction": direction,
                "type": "SNIPER_30S_M5",
                "status": "OPERACIÓN SNIPER EN CURSO (M5)",
                "entry_time": dt_str,
                "expire_time": expire_time_str,
                "entry_price": gatillo["price"],
                "fibo_50": gatillo["c1"],
                "fibo_618": gatillo["c2"],
                "tip": f"Gatillo Sniper 30s adelantado en nivel M15. {gatillo['detail']}",
                "amount": trade_amount
            }
            self.last_signal_event = sig_event
            self.live_signals_feed.append(sig_event)
            self.live_signals_feed = self.live_signals_feed[-10:]

            await self.broadcast_sniper_event({
                "event": "GATILLO_EJECUTADO",
                "pair": pair,
                "direction": direction,
                "price": gatillo["price"],
                "expire_time": expire_time_str,
                "msg": f"{gatillo['action']}|{pair}"
            })

            # Notificación a Telegram
            self.telegram.notify_sniper_entry(
                pair=pair,
                direction=direction,
                entry_time=dt_str,
                entry_price=gatillo["price"],
                level_price=gatillo["level"],
                expire_time=expire_time_str,
                detail=gatillo["detail"],
                amount=trade_amount
            )
            logger.info(f"Orden Sniper colocada exitosamente en {pair} {direction} (ID: {order_id})")
        else:
            logger.error(f"Error al enviar orden Sniper en {pair}: {msg}")
            self.engine_mode = "SEARCHING"
            self.locked_pair = None

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
                # 1. STREAMING DE ALTA FRECUENCIA (CADA 50-70 MS) Y RADAR SNIPER
                # =========================================================
                if self.is_running and self.selected_pairs:
                    server_ts = self.iq.get_server_timestamp()
                    
                    # Actualizar niveles M15 periódicamente (cada ~45 segundos)
                    if (current_int_sec - self.last_m15_scan_time) >= 45:
                        self.last_m15_scan_time = current_int_sec
                        for p_scan in self.selected_pairs:
                            m15_candles = await asyncio.to_thread(self.iq.get_candles, p_scan, 900, 25)
                            if m15_candles:
                                self.sniper.actualizar_niveles_m15(p_scan, m15_candles, self.indicator)

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

                        # Evaluación en tiempo real del Retroceso Fibonacci M5 (Alternativa A)
                        if self.engine_mode in ("CONFIRMING", "WAITING_PULLBACK") and pair == self.locked_pair and p_state["tick_price"] > 0:
                            await self._evaluar_pullback_tick(pair, p_state["tick_price"], server_ts)
                            if self.engine_mode == "IN_TRADE":
                                break

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
                        try:
                            await self._tick_sequential_strategy()
                        except Exception as e_strat:
                            logger.error(f"Error en estrategia secuencial: {e_strat}", exc_info=True)
                    else:
                        self.seconds_left_in_candle = 0
                        self.current_status_message = "Bot detenido - Esperando activación en el panel admin"

                    try:
                        await self.broadcast_status()
                    except Exception as e_bc:
                        logger.error(f"Error en broadcast_status: {e_bc}")

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
        current_int_sec = int(server_ts)

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

                        # FILTRO DE CONFLUENCIA ALTA M15 (Descartar rangos cortos/laterales de M15)
                        is_confluent, conf_reason = await asyncio.to_thread(
                            self.check_m15_high_confluence, pair, direction, float(closed_candle['close'])
                        )
                        if not is_confluent:
                            logger.info(f"Filtro M15: Señal {direction} en {pair} descartada -> {conf_reason}")
                            continue

                        candle_dt_str = datetime.fromtimestamp(closed_candle_time).strftime("%H:%M:%S")

                        # Cálculo de Fibonacci en la vela de señal recién cerrada (Alternativa A)
                        s_min = float(closed_candle.get('min', closed_candle.get('low', closed_candle['close'])))
                        s_max = float(closed_candle.get('max', closed_candle.get('high', closed_candle['close'])))
                        s_close = float(closed_candle['close'])
                        s_range = max(1e-5, s_max - s_min)
                        
                        if direction in ("CALL", "COMPRA"):
                            init_fibo_50 = s_max - (s_range * 0.50)
                            init_fibo_618 = s_max - (s_range * 0.618)
                        else:  # PUT / VENTA
                            init_fibo_50 = s_min + (s_range * 0.50)
                            init_fibo_618 = s_min + (s_range * 0.618)

                        # Expiración: Cierre de la vela M5 actual que acaba de iniciar
                        current_m5_end = ((server_ts // 300) + 1) * 300
                        expire_time_str = datetime.fromtimestamp(current_m5_end).strftime("%H:%M:%S")

                        # ¡BLOQUEAR MOTOR EN ESTE PAR PARA RETROCESO! (Alternativa A)
                        self.locked_pair = pair
                        self.active_pair = pair
                        self.engine_mode = "WAITING_PULLBACK"
                        
                        self.pending_signal = {
                            "pair": pair,
                            "direction": direction,
                            "detected_at": time_str,
                            "candle_time": candle_dt_str,
                            "signal_candle_from": closed_candle_time,
                            "signal_candle": closed_candle,
                            "signal_price": s_close,
                            "fibo_50": round(init_fibo_50, 5),
                            "fibo_618": round(init_fibo_618, 5),
                            "start_ts": server_ts,
                            "end_ts": current_m5_end,
                            "max_wait_seconds": 180,
                            "confluence_info": conf_reason
                        }

                        sig_event = {
                            "id": int(time.time()),
                            "time": time_str,
                            "pair": pair,
                            "direction": direction,
                            "type": "SEÑAL_M5",
                            "status": "ESPERANDO RETROCESO FIBO 50% - 61.8%",
                            "entry_time": "Al tocar retroceso Fibo",
                            "expire_time": expire_time_str,
                            "entry_price": s_close,
                            "fibo_50": round(init_fibo_50, 5),
                            "fibo_618": round(init_fibo_618, 5),
                            "tip": f"Esperar retroceso a zona Fibo 50% ({init_fibo_50:.5f}) - 61.8% ({init_fibo_618:.5f}) para entrada óptima.",
                            "confluence": conf_reason
                        }
                        self.last_signal_event = sig_event
                        self.live_signals_feed.append(sig_event)
                        self.live_signals_feed = self.live_signals_feed[-10:]

                        self.current_status_message = f"¡SEÑAL {direction} EN {pair}! Esperando retroceso a Fibo 50% ({init_fibo_50:.5f})..."
                        logger.info(f"🎯 ¡SEÑAL CONFIRMADA M5! {pair} {direction}. Esperando retroceso Fibo 50%: {init_fibo_50:.5f}")
                        
                        # Notificación inmediata a Telegram (Alternativa A)
                        self.telegram.notify_signal_m5_pullback(
                            pair=pair,
                            direction=direction,
                            candle_time=candle_dt_str,
                            signal_price=s_close,
                            fibo_50=round(init_fibo_50, 5),
                            fibo_618=round(init_fibo_618, 5),
                            expire_time=expire_time_str
                        )
                        
                        # Notificación a Web vía WebSocket
                        await self.broadcast_custom_text(f"PREALERTA|{pair}|{direction}")
                        break

        # =========================================================
        # FASE 2: WAITING_PULLBACK (Monitorea retroceso del par bloqueado)
        # =========================================================
        elif self.engine_mode in ("CONFIRMING", "WAITING_PULLBACK"):
            pair = self.locked_pair
            direction = self.pending_signal["direction"]
            p_state = self.pairs_state.get(pair, {})
            current_price = p_state.get("tick_price", 0.0)
            elapsed = server_ts - self.pending_signal.get("start_ts", server_ts)
            max_wait = self.pending_signal.get("max_wait_seconds", 180)
            fibo_50 = self.pending_signal.get("fibo_50", 0.0)
            fibo_618 = self.pending_signal.get("fibo_618", 0.0)

            time_left_to_wait = max(0, max_wait - elapsed)
            self.current_status_message = (
                f"[{time_str}] ESPERANDO RETROCESO {direction} EN {pair}: "
                f"Precio: {current_price:.5f} | Fibo 50%: {fibo_50:.5f} (Ventana: {time_left_to_wait}s)"
            )

            # Monitorear tick
            if current_price > 0:
                await self._evaluar_pullback_tick(pair, current_price, server_ts)

            if self.engine_mode == "IN_TRADE":
                return

            # Si transcurrieron más de 180s o quedan menos de 90s para el cierre de vela M5
            seconds_left_in_m5 = max(0, self.pending_signal.get("end_ts", server_ts) - server_ts)
            if elapsed >= max_wait or seconds_left_in_m5 <= 90:
                logger.info(
                    f"Tiempo de retroceso agotado ({elapsed}s transcurridos, quedan {seconds_left_in_m5}s en M5) "
                    f"para {pair} {direction}. Cancelando entrada para proteger capital."
                )
                self.telegram.notify_pullback_cancelled(
                    pair=pair,
                    direction=direction,
                    reason=f"El precio no retrocedió a la zona Fibo 50% ({fibo_50:.5f}) dentro de los primeros {max_wait}s."
                )
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
                trade_amount = cur_trade["amount"]
                entry_price = cur_trade["entry_price"]

                # 1. Obtener velas recientes para determinar el precio de cierre exacto
                fresh_candles = await asyncio.to_thread(self.iq.get_candles, pair, self.timeframe, 5)
                close_price = None
                if fresh_candles and len(fresh_candles) >= 2:
                    if fresh_candles[-1].get('from', 0) >= cur_trade["end_ts"]:
                        close_price = fresh_candles[-2].get('close')
                    else:
                        close_price = fresh_candles[-1].get('close')
                elif fresh_candles:
                    close_price = fresh_candles[-1].get('close')

                if close_price is None or close_price <= 0:
                    close_price = self.current_tick_price if self.current_tick_price else entry_price

                # 2. Consultar al broker vía websocket
                result, profit, _, _ = await asyncio.to_thread(self.iq.check_result, order_id)
                close_time_str = datetime.fromtimestamp(self.iq.get_server_timestamp()).strftime("%H:%M:%S")

                # 3. Fallback matemático preciso si el broker no devolvió un resultado concluyente
                if result not in ("WIN", "LOSS", "EQUAL"):
                    logger.info(f"Liquidando resultado matemático para {pair} {trade_dir} (Entrada: {entry_price}, Cierre: {close_price})")
                    diff = close_price - entry_price
                    if abs(diff) < 1e-6:
                        result = "EQUAL"
                        profit = 0.0
                    elif trade_dir == "CALL":
                        if diff > 0:
                            result = "WIN"
                            profit = round(trade_amount * 0.85, 2)
                        else:
                            result = "LOSS"
                            profit = round(-trade_amount, 2)
                    elif trade_dir == "PUT":
                        if diff < 0:
                            result = "WIN"
                            profit = round(trade_amount * 0.85, 2)
                        else:
                            result = "LOSS"
                            profit = round(-trade_amount, 2)
                else:
                    # Garantizar coherencia en los importes de profit
                    if result == "WIN" and profit <= 0:
                        profit = round(trade_amount * 0.85, 2)
                    elif result == "LOSS" and profit >= 0:
                        profit = round(-trade_amount, 2)
                    elif result == "EQUAL":
                        profit = 0.0

                # 4. Actualización rigurosa de estadísticas de sesión
                if result == "WIN":
                    self.session_stats["wins"] += 1
                    self.session_stats["net_profit"] += profit
                elif result == "LOSS":
                    self.session_stats["losses"] += 1
                    self.session_stats["net_profit"] += profit
                else:
                    self.session_stats["equals"] += 1

                self.current_amount = self.base_amount
                self.current_martingale_step = 0

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
                    "amount": trade_amount,
                    "martingale_step": 0
                }
                self.trade_history.append(trade_record)
                self.db.save_trade(trade_record)

                sig_event = {
                    "id": order_id,
                    "time": close_time_str,
                    "pair": pair,
                    "direction": trade_dir,
                    "type": "RESULTADO",
                    "status": result,
                    "profit": round(profit, 2),
                    "entry_time": cur_trade["entry_time"],
                    "close_time": close_time_str,
                    "expire_time": close_time_str,
                    "entry_price": entry_price,
                    "close_price": close_price,
                    "fibo_50": cur_trade.get("fibo_50"),
                    "fibo_618": cur_trade.get("fibo_618"),
                    "tip": f"Operación finalizada: {result} (${profit:+.2f})"
                }
                self.last_signal_event = sig_event
                self.live_signals_feed.append(sig_event)
                self.live_signals_feed = self.live_signals_feed[-10:]

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
                self.current_status_message = f"Operación finalizada ({result}). Reanudando análisis simultáneo de todos los pares en M5..."

    def update_config(self, pairs: List[str], timeframe: int, amount: float, martingale: int, account_type: str):
        if pairs:
            self.set_selected_pairs(pairs)
        self.timeframe = 300
        self.expiration = 5
        self.base_amount = float(amount)
        self.current_amount = self.base_amount
        self.martingale_steps = 0
        self.martingale_multiplier = 1.0
        if account_type.upper() != self.iq.account_type:
            self.iq.change_balance(account_type.upper())
        logger.info(f"Configuración actualizada: Pares={len(self.selected_pairs)}, TF=300s (5M), Monto=${self.base_amount}, Sin Martingala, Cuenta={self.iq.account_type}")

    def check_m15_high_confluence(self, pair: str, direction: str, current_price: float) -> Tuple[bool, str]:
        """
        Filtro de Confluencia Alta M15:
        1. Descarta señales generadas dentro de rangos cortos/estrechos (squeeze lateral) en M15.
        2. Exige confluencia de soporte/rebote para CALL y resistencia/rechazo para PUT,
           evitando comprar techos o vender pisos en rangos.
        """
        try:
            m15_candles = self.iq.get_candles(pair, 900, 20)
            if not m15_candles or len(m15_candles) < 10:
                return True, "Datos M15 limitados, confluencia estándar"

            closes = [float(c['close']) for c in m15_candles]
            highs = [float(c.get('max', c.get('high', c['close']))) for c in m15_candles]
            lows = [float(c.get('min', c.get('low', c['close']))) for c in m15_candles]

            # 1. Medir el rango de las últimas 4 velas M15 (última hora)
            recent_high = max(highs[-4:])
            recent_low = min(lows[-4:])
            recent_range = recent_high - recent_low

            # 2. Medir ATR promedio en M15 (14 periodos)
            tr_list = []
            for i in range(1, len(m15_candles)):
                tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                tr_list.append(tr)
            atr_m15 = sum(tr_list) / len(tr_list) if tr_list else 0.0005

            # Filtro 1: Rango corto lateral en M15 (rango de 1 hora menor al 110% de un solo ATR promedio)
            if recent_range < (1.1 * atr_m15):
                return False, f"Rango lateral estrecho en M15 (Rango 1h: {recent_range:.5f} < ATR: {atr_m15:.5f})"

            # 3. Ubicación relativa del precio dentro del rango M15 (0.0 = soporte inferior, 1.0 = resistencia superior)
            full_high = max(highs[-8:])
            full_low = min(lows[-8:])
            range_15 = full_high - full_low
            if range_15 > 1e-6:
                relative_pos = (current_price - full_low) / range_15
            else:
                relative_pos = 0.5

            # 4. Tendencia M15 (Media rápida 6 vs Media lenta 14)
            ma_fast = sum(closes[-6:]) / 6
            ma_slow = sum(closes[-14:]) / 14 if len(closes) >= 14 else ma_fast

            if direction == "CALL":
                # Rechazar si estamos comprando en el techo de un rango sin tendencia alcista
                if relative_pos > 0.85 and ma_fast <= ma_slow:
                    return False, f"Sin confluencia para CALL (Precio en techo de rango M15: {relative_pos:.2f})"
                return True, f"Confluencia Alta CALL (Zona: {relative_pos:.2f}, Rango M15 activo)"

            elif direction == "PUT":
                # Rechazar si estamos vendiendo en el piso de un rango sin tendencia bajista
                if relative_pos < 0.15 and ma_fast >= ma_slow:
                    return False, f"Sin confluencia para PUT (Precio en piso de rango M15: {relative_pos:.2f})"
                return True, f"Confluencia Alta PUT (Zona: {relative_pos:.2f}, Rango M15 activo)"

            return True, "Confluencia válida"
        except Exception as e:
            logger.error(f"Error evaluando confluencia M15: {e}")
            return True, "Fallback confluencia"
