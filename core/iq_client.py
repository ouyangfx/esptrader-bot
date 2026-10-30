"""
Cliente de Conexión y Ejecución para IQ Option API
Maneja autenticación, cambio de saldo (PRACTICE/REAL), obtención de velas en tiempo real,
verificación de expiración y colocación de operaciones binarias a 1 minuto.
Incluye modo simulación/fallback si no hay credenciales configuradas aún.
"""

import time
import json
import logging
import random
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# =====================================================================
# PARCHE DE SEGURIDAD CRÍTICO ANTI-DEADLOCK PARA IQOPTIONAPI
# Previene bucles infinitos a 100% CPU si la conexión se interrumpe
# =====================================================================
try:
    import iqoptionapi.global_value as iq_global
    import iqoptionapi.api as iq_api_mod
    import iqoptionapi.stable_api as iq_stable
    from iqoptionapi.constants import OP_code
    
    def safe_send_websocket_request(self, name, msg, request_id="", no_force_send=True):
        data = json.dumps(dict(name=name, msg=msg, request_id=request_id))
        start_wait = time.time()
        while (iq_global.ssl_Mutual_exclusion or iq_global.ssl_Mutual_exclusion_write) and no_force_send:
            time.sleep(0.01)  # Ceder CPU siempre
            if time.time() - start_wait > 2.0:
                # Romper bloqueo si la conexión o thread anterior murió
                iq_global.ssl_Mutual_exclusion = False
                iq_global.ssl_Mutual_exclusion_write = False
                break

        iq_global.ssl_Mutual_exclusion_write = True
        try:
            if hasattr(self, 'websocket') and self.websocket:
                self.websocket.send(data)
        except Exception:
            pass
        finally:
            iq_global.ssl_Mutual_exclusion_write = False

    def safe_get_candles(self, ACTIVES, interval, count, endtime):
        """Versión sin bloqueos ni 100% CPU de get_candles con timeout estricto de 3.5s."""
        self.api.candles.candles_data = None
        active_code = OP_code.ACTIVES.get(ACTIVES, ACTIVES)
        start_wait = time.time()
        while time.time() - start_wait < 3.5:
            try:
                self.api.getcandles(active_code, interval, count, endtime)
                inner_wait = time.time()
                while self.api.candles.candles_data is None:
                    time.sleep(0.02)  # Ceder CPU siempre
                    if time.time() - inner_wait > 1.5:
                        break
                if self.api.candles.candles_data is not None:
                    return self.api.candles.candles_data
            except Exception:
                time.sleep(0.1)
                break
            time.sleep(0.05)
        return self.api.candles.candles_data

    def safe_buy(self, price, ACTIVES, ACTION, expirations):
        """Versión sin busy-wait de buy con time.sleep(0.02) y timeout de 4.0s."""
        self.api.buy_multi_option = {}
        self.api.buy_successful = None
        req_id = "buy"
        try:
            self.api.buy_multi_option[req_id]["id"] = None
        except Exception:
            pass
        active_code = OP_code.ACTIVES.get(ACTIVES, ACTIVES)
        try:
            self.api.buyv3(price, active_code, ACTION, expirations, req_id)
        except Exception as e:
            return False, str(e)
            
        start_t = time.time()
        order_id = None
        self.api.result = None
        while self.api.result is None or order_id is None:
            time.sleep(0.02)  # Ceder CPU siempre
            try:
                if req_id in self.api.buy_multi_option and "message" in self.api.buy_multi_option[req_id]:
                    return False, self.api.buy_multi_option[req_id]["message"]
            except Exception:
                pass
            try:
                if req_id in self.api.buy_multi_option:
                    order_id = self.api.buy_multi_option[req_id].get("id")
            except Exception:
                pass
            if time.time() - start_t >= 4.0:
                logger.warning(f"Timeout esperando confirmación de compra para {ACTIVES}")
                return False, "Timeout esperando respuesta del broker"

        return self.api.result, order_id

    iq_api_mod.IQOptionAPI.send_websocket_request = safe_send_websocket_request
    iq_stable.IQ_Option.get_candles = safe_get_candles
    iq_stable.IQ_Option.buy = safe_buy
    logger.info("Parches anti-deadlock (websocket, get_candles, buy) aplicados a iqoptionapi con éxito.")
except Exception as e_patch:
    logger.warning(f"No se pudo aplicar parches anti-deadlock a iqoptionapi: {e_patch}")

class IQOptionClient:
    def __init__(self, email: str = "", password: str = "", account_type: str = "PRACTICE"):
        self.email = email
        self.password = password
        self.account_type = account_type.upper()
        self.api = None
        self.is_connected = False
        self.is_simulation = False
        self.mock_balance = 10000.0 if self.account_type == "PRACTICE" else 100.0
        self.cached_balance = 0.0
        self._last_balance_time = 0.0
        self._last_reconnect_attempt = 0.0
        self.streaming_pairs = set()
        self.realtime_prices: Dict[str, float] = {}

    def start_streams(self, pairs: List[str], timeframe: int):
        """Inicia el streaming de velas y ticks en tiempo real para los pares seleccionados."""
        self.streaming_pairs = set(p.upper() for p in pairs)
        if not self.is_simulation and self.api:
            for p in self.streaming_pairs:
                try:
                    self.api.start_candles_stream(p, timeframe, 10)
                    logger.info(f"Stream de velas y ticks iniciado para {p} ({timeframe}s)")
                except Exception as e:
                    logger.error(f"Error iniciando candle stream para {p}: {e}")

    def stop_streams(self, timeframe: int):
        """Detiene el streaming de velas."""
        if not self.is_simulation and self.api:
            for p in list(self.streaming_pairs):
                try:
                    self.api.stop_candles_stream(p, timeframe)
                except Exception:
                    pass
        self.streaming_pairs.clear()

    def get_realtime_price(self, pair: str, timeframe: int) -> float:
        """
        Retorna el precio tick instantáneo al microsegundo.
        En cuenta real/demo se alimenta del websocket de IQ Option en tiempo real.
        En simulación genera micro-fluctuaciones realistas de alta frecuencia (sub-segundo).
        """
        pair_clean = pair.upper()
        if not self.is_simulation and self.api:
            try:
                rt = self.api.get_realtime_candles(pair_clean, timeframe)
                if rt and isinstance(rt, dict):
                    latest_ts = max(rt.keys())
                    candle = rt[latest_ts]
                    price = float(candle.get('close', candle.get('open', 0.0)))
                    if price > 0:
                        self.realtime_prices[pair_clean] = price
                        return price
            except Exception:
                pass

        # Generador de micro-ticks de alta frecuencia
        if pair_clean not in self.realtime_prices:
            base_prices = {
                "EURUSD": 1.08500, "GBPUSD": 1.26500, "USDJPY": 154.500, "EURJPY": 167.200
            }
            clean_key = pair_clean.replace("-OTC", "")
            self.realtime_prices[pair_clean] = base_prices.get(clean_key, 1.08500)

        # Micro-fluctuación continua sub-segundo (+/- 1 a 3 micro-pips)
        scale = 0.003 if "JPY" in pair_clean else 0.00002
        delta = (random.random() - 0.495) * scale
        decimals = 3 if "JPY" in pair_clean else 5
        new_price = round(self.realtime_prices[pair_clean] + delta, decimals)
        self.realtime_prices[pair_clean] = new_price
        return new_price

    def test_connection(self, email: str, password: str, account_type: str = "PRACTICE") -> Dict[str, Any]:
        """Prueba credenciales y conexión directa a IQ Option sin alterar el bot."""
        if not email or not password or "tu_correo" in email:
            return {
                "success": False,
                "message": "Por favor ingresa un email y contraseña válidos de IQ Option.",
                "balance": 0.0,
                "account_type": account_type.upper(),
                "is_simulation": True
            }

        try:
            try:
                from iqoptionapi.stable_api import IQ_Option
            except ImportError:
                from iqoptionapi.api import IQOptionAPI as IQ_Option
            
            api = IQ_Option(email.strip(), password.strip())
            check, reason = api.connect()

            if check:
                self.api = api
                self.email = email.strip()
                self.password = password.strip()
                self.account_type = account_type.upper()
                self.is_connected = True
                self.is_simulation = False
                
                # Sincronizar tipo de cuenta y saldo
                self.change_balance(self.account_type)
                balance = self.get_balance()
                msg = f"Conexión exitosa a IQ Option ({self.account_type}). Saldo real verificado: ${balance:,.2f}"
                logger.info(msg)
                return {
                    "success": True,
                    "message": msg,
                    "balance": balance,
                    "account_type": self.account_type,
                    "is_simulation": False
                }
            else:
                logger.warning(f"Fallo de conexión en test IQ Option: {reason}")
                return {
                    "success": False,
                    "message": f"No se pudo conectar a IQ Option: {reason}. Verifica tus credenciales.",
                    "balance": 0.0,
                    "account_type": account_type.upper(),
                    "is_simulation": True
                }
        except Exception as e:
            logger.error(f"Excepción en test_connection: {e}")
            return {
                "success": False,
                "message": f"Error al inicializar conexión con IQ Option API: {str(e)}",
                "balance": 0.0,
                "account_type": account_type.upper(),
                "is_simulation": True
            }

    def connect(self) -> Tuple[bool, str]:
        """Intenta conectar a IQ Option con las credenciales provistas."""
        if not self.email or not self.password or "tu_correo" in self.email:
            self.is_connected = True
            self.is_simulation = True
            msg = "Credenciales no configuradas. Iniciando en MODO SIMULACIÓN SEGURO."
            logger.info(msg)
            return True, msg

        try:
            from iqoptionapi.stable_api import IQ_Option
            self.api = IQ_Option(self.email, self.password)
            check, reason = self.api.connect()
            
            if check:
                self.is_connected = True
                self.is_simulation = False
                # Cambiar cuenta
                self.change_balance(self.account_type)
                balance = self.get_balance()
                msg = f"Conexión exitosa a IQ Option ({self.account_type}). Saldo: ${balance:.2f}"
                logger.info(msg)
                return True, msg
            else:
                self.is_connected = True
                self.is_simulation = True
                msg = f"No se pudo conectar a IQ Option ({reason}). Activando MODO SIMULACIÓN."
                logger.warning(msg)
                return True, msg
        except Exception as e:
            self.is_connected = True
            self.is_simulation = True
            msg = f"Error al inicializar iqoptionapi: {str(e)}. Activando MODO SIMULACIÓN."
            logger.error(msg)
            return True, msg

    def change_balance(self, account_type: str):
        self.account_type = account_type.upper()
        if self.is_simulation or not self.api:
            return
        try:
            self.api.change_balance(self.account_type)
        except Exception as e:
            logger.error(f"Error cambiando tipo de cuenta: {e}")

    def check_and_reconnect(self) -> bool:
        """Verifica el estado del socket con IQ Option y reconecta de forma transparente si se cayó."""
        if self.is_simulation or not self.api:
            return True

        now = time.time()
        # Evitar reintentos excesivos seguidos (máximo 1 intento cada 15 segundos)
        if (now - self._last_reconnect_attempt) < 15.0:
            return self.is_connected

        try:
            is_active = False
            if hasattr(self.api, "check_connect"):
                is_active = self.api.check_connect()
            elif hasattr(self.api, "websocket") and self.api.websocket:
                is_active = getattr(self.api.websocket, "connected", False)

            if not is_active:
                self._last_reconnect_attempt = now
                logger.warning("⚠️ Conexión perdida con IQ Option. Intentando reconexión automática en segundo plano...")
                check, reason = self.api.connect()
                if check:
                    self.is_connected = True
                    self.is_simulation = False
                    self.change_balance(self.account_type)
                    if self.streaming_pairs:
                        for p in list(self.streaming_pairs):
                            try:
                                self.api.start_candles_stream(p, 300, 10)
                            except Exception:
                                pass
                    logger.info("✅ Reconexión automática a IQ Option exitosa y streams restaurados.")
                    return True
                else:
                    logger.warning(f"Reconexión a IQ Option falló ({reason}). Reintentará en el siguiente ciclo.")
                    return False
            return True
        except Exception as e:
            logger.error(f"Error verificando conexión IQ Option: {e}")
            return False

    def get_balance(self, force: bool = False) -> float:
        if self.is_simulation or not self.api:
            return float(self.mock_balance)

        now = time.time()
        # Cache de 15 segundos para no saturar el websocket cada segundo
        if not force and self.cached_balance > 0 and (now - self._last_balance_time) < 15.0:
            return self.cached_balance

        try:
            self.check_and_reconnect()
            bal = self.api.get_balance()
            if bal is not None and float(bal) >= 0:
                self.cached_balance = float(bal)
                self._last_balance_time = now
                return self.cached_balance
            return self.cached_balance if self.cached_balance > 0 else 0.0
        except Exception as e:
            logger.error(f"Error obteniendo balance: {e}")
            return self.cached_balance if self.cached_balance > 0 else 0.0

    def get_server_timestamp(self) -> int:
        if self.is_simulation or not self.api:
            return int(time.time())
        try:
            return int(self.api.get_server_timestamp())
        except Exception:
            return int(time.time())

    def get_candles(self, active: str, timeframe: int, count: int = 150) -> List[Dict]:
        """
        active: 'EURUSD', 'GBPUSD', etc.
        timeframe: segundos (60 para 1m, 300 para 5m)
        count: número de velas a traer (cubre hasta 24 horas del último día)
        """
        if self.is_simulation or not self.api:
            return self._generate_simulated_candles(active, timeframe, count)

        try:
            # iqoptionapi get_candles con timestamp actual para obtener el último día en tiempo real
            candles = self.api.get_candles(active, timeframe, count, int(time.time()))
            if candles and isinstance(candles, list):
                # Asegurar formato estándar, orden cronológico y sin duplicados
                std_candles = []
                for c in candles:
                    std_candles.append({
                        'id': c.get('id', 0),
                        'from': int(c.get('from', 0)),
                        'to': int(c.get('to', 0)),
                        'open': float(c.get('open', 0)),
                        'close': float(c.get('close', 0)),
                        'min': float(c.get('min', c.get('low', 0))),
                        'max': float(c.get('max', c.get('high', 0))),
                        'volume': float(c.get('volume', 0))
                    })
                std_candles.sort(key=lambda x: x['from'])
                unique_candles = []
                seen_from = set()
                for c in std_candles:
                    if c['from'] not in seen_from:
                        seen_from.add(c['from'])
                        unique_candles.append(c)
                if len(unique_candles) >= 5:
                    return unique_candles
            return self._generate_simulated_candles(active, timeframe, count)
        except Exception as e:
            logger.error(f"Error obteniendo velas de {active}: {e}")
            return self._generate_simulated_candles(active, timeframe, count)

    def buy_option(self, active: str, amount: float, action: str, expiration: int = 1) -> Tuple[bool, Optional[int], str]:
        """
        active: EURUSD
        amount: monto en USD
        action: 'CALL' o 'PUT'
        expiration: minutos (1)
        """
        action = action.upper()
        if self.is_simulation or not self.api:
            mock_id = int(time.time() * 1000) % 10000000
            logger.info(f"[SIMULACIÓN] Compra ejecutada: {active} {action} ${amount:.2f} exp: {expiration}m (ID: {mock_id})")
            return True, mock_id, "OK_SIMULATED"

        try:
            check, order_id = self.api.buy(amount, active, action.lower(), expiration)
            if check:
                logger.info(f"Operación enviada: {active} {action} ${amount} (ID: {order_id})")
                return True, order_id, "OK"
            else:
                logger.warning(f"Fallo al enviar operación a IQ Option: {order_id}")
                return False, None, str(order_id)
        except Exception as e:
            logger.error(f"Excepción en buy_option: {e}")
            return False, None, str(e)

    def check_result(self, order_id: int, timeout: int = 8) -> Tuple[str, float, float, float]:
        """
        Espera y retorna (resultado, profit, precio_apertura, precio_cierre)
        resultado: 'WIN', 'LOSS', 'EQUAL' o 'UNKNOWN'
        """
        if self.is_simulation or not self.api:
            return "WIN" if random.random() > 0.35 else "LOSS", 1.74, 1.08500, 1.08520

        # Monitorear respuestas websocket del broker durante 'timeout' segundos sin bloquear
        start_t = time.time()
        while time.time() - start_t < timeout:
            try:
                # 1. order_async (streaming en vivo de option-closed)
                if hasattr(self.api, "order_async") and order_id in self.api.order_async:
                    ord_info = self.api.order_async.get(order_id, {})
                    if ord_info and "option-closed" in ord_info and ord_info["option-closed"]:
                        msg = ord_info["option-closed"].get("msg", {})
                        win_state = str(msg.get("win", "")).lower()
                        profit_amount = float(msg.get("profit_amount", 0.0))
                        bet_amount = float(msg.get("amount", 0.0))
                        net_profit = profit_amount - bet_amount
                        if win_state == "win" or net_profit > 0:
                            return "WIN", round(net_profit, 2), 0.0, 0.0
                        elif win_state in ("loose", "loss") or net_profit < 0:
                            return "LOSS", round(-bet_amount, 2), 0.0, 0.0
                        elif win_state == "equal":
                            return "EQUAL", 0.0, 0.0, 0.0

                # 2. listinfodata (streaming en vivo de listInfoData sin bucle infinito)
                if hasattr(self.api, "listinfodata") and hasattr(self.api.listinfodata, "listinfodata_dict"):
                    info = self.api.listinfodata.listinfodata_dict.get(order_id)
                    if info and info.get("game_state") == 1:
                        win_str = str(info.get("win", "")).lower()
                        if "win" in win_str:
                            return "WIN", 0.0, 0.0, 0.0
                        elif "loose" in win_str or "loss" in win_str:
                            return "LOSS", 0.0, 0.0, 0.0
                        elif "equal" in win_str:
                            return "EQUAL", 0.0, 0.0, 0.0
            except Exception as e:
                logger.debug(f"Error verificando resultado en websocket: {e}")

            time.sleep(0.5)

        logger.info(f"El broker aún no liquidó vía websocket el trade ID {order_id}. Se procederá a verificación matemática por velas.")
        return "UNKNOWN", 0.0, 0.0, 0.0

    def _generate_simulated_candles(self, active: str, timeframe: int, count: int) -> List[Dict]:
        """Generador determinista/aleatorio de velas para pruebas realistas."""
        now = int(time.time())
        # Alinear a inicio de vela
        now_aligned = now - (now % timeframe)
        candles = []
        
        pair_clean = active.upper().replace("-OTC", "")
        base_prices = {
            "EURUSD": 1.08500,
            "GBPUSD": 1.26500,
            "USDJPY": 154.500,
            "EURJPY": 167.200,
            "AUDUSD": 0.65500,
            "USDCAD": 1.38500,
            "USDCHF": 0.90200,
            "EURGBP": 0.85800,
            "NZDUSD": 0.59800,
            "GBPJPY": 195.400
        }
        base_price = base_prices.get(pair_clean, 1.08500)
        spread_scale = 0.05 if "JPY" in pair_clean else 0.0003
        
        for i in range(count):
            t_from = now_aligned - ((count - i) * timeframe)
            t_to = t_from + timeframe
            delta = (random.random() - 0.49) * (spread_scale * 2)
            close_p = base_price + delta
            high_p = max(base_price, close_p) + (random.random() * spread_scale)
            low_p = min(base_price, close_p) - (random.random() * spread_scale)
            
            decimals = 3 if "JPY" in pair_clean else 5
            candles.append({
                'id': i,
                'from': t_from,
                'to': t_to,
                'open': round(base_price, decimals),
                'close': round(close_p, decimals),
                'min': round(low_p, decimals),
                'max': round(high_p, decimals),
                'volume': random.randint(10, 100)
            })
            base_price = close_p
        return candles
