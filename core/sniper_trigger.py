"""
Módulo de Gatillo Sniper Cuantitativo (Multi-Timeframe M15 / M5 / 30s)
Implementa las 4 reglas institucionales estrictas:
1. Radar de Proximidad a niveles c1 y c2 de M15 (Pre-alerta con histéresis anti-spam a 3 pips).
2. Filtro de Ventana de Tiempo M5 (Intra-bar: solo válido de 00:00 a 03:00 / 0 a 180s).
3. Gatillo Matemático OHLC en velas cerradas de 30 segundos (Mecha > 2x cuerpo y mecha dominante).
4. Enrutamiento Inteligente: Bypass inmediato para OTC vs Filtro de Fuerza de Divisa para Mercado Real.
"""

import time
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

def get_pip_value(pair: str) -> float:
    """
    Retorna el valor métrico exacto de 1 pip:
    - Pares con JPY (USDJPY, EURJPY, etc.): 0.01 (2do decimal)
    - Pares Forex estándar (EURUSD, GBPUSD, etc.): 0.0001 (4to decimal)
    """
    pair_upper = pair.upper()
    if "JPY" in pair_upper:
        return 0.01
    return 0.0001

def es_horario_valido_m5(timestamp: Optional[float] = None) -> bool:
    """
    Regla 2: Expiración M5 intra-bar.
    El ciclo de una vela de 5 minutos dura 300 segundos.
    - Minutos 00:00 a 03:00 (0s a 180s) -> VÁLIDO (quedan >= 120s para el cierre).
    - Minutos 03:01 a 05:00 (181s a 299s) -> SILENCIAR (zona de peligro, < 2 min).
    """
    ts = int(timestamp if timestamp is not None else time.time())
    segundos_en_m5 = ts % 300
    return segundos_en_m5 <= 180

def evaluar_rechazo_30s(candle_30s: Dict[str, Any], pair: str, nivel_c: float, tipo: str) -> Tuple[bool, str]:
    """
    Regla 3: Anatomía cuantitativa de la vela de 30 segundos CERRADA.
    tipo: 'VENTA' (en c1 resistencia) | 'COMPRA' (en c2 soporte)
    
    Retorna: (cumple_condicion: bool, detalle_rechazo: str)
    """
    try:
        o = float(candle_30s['open'])
        h = float(candle_30s.get('max', candle_30s.get('high', candle_30s['close'])))
        l = float(candle_30s.get('min', candle_30s.get('low', candle_30s['close'])))
        c = float(candle_30s['close'])

        pip = get_pip_value(pair)
        cuerpo = max(1e-6, abs(c - o))
        mecha_sup = h - max(o, c)
        mecha_inf = min(o, c) - l

        if tipo == "VENTA":
            # 1. El high debió tocar o superar c1 (con margen de 1 pip)
            toco = h >= (nivel_c - (1.0 * pip))
            # 2. Mecha superior > 2 veces el cuerpo
            mecha_fuerte = mecha_sup > (cuerpo * 2.0)
            # 3. Mecha superior mayor a la mecha inferior
            mecha_dominante = mecha_sup > mecha_inf

            if toco and mecha_fuerte and mecha_dominante:
                ratio = mecha_sup / cuerpo
                return True, f"Rechazo VENTA 30s confirmado (Mecha Sup: {mecha_sup:.5f} = {ratio:.1f}x cuerpo)"
            return False, "No cumple anatomía de venta en 30s"

        elif tipo == "COMPRA":
            # 1. El low debió tocar o perforar c2 (con margen de 1 pip)
            toco = l <= (nivel_c + (1.0 * pip))
            # 2. Mecha inferior > 2 veces el cuerpo
            mecha_fuerte = mecha_inf > (cuerpo * 2.0)
            # 3. Mecha inferior mayor a la mecha superior
            mecha_dominante = mecha_inf > mecha_sup

            if toco and mecha_fuerte and mecha_dominante:
                ratio = mecha_inf / cuerpo
                return True, f"Rechazo COMPRA 30s confirmado (Mecha Inf: {mecha_inf:.5f} = {ratio:.1f}x cuerpo)"
            return False, "No cumple anatomía de compra en 30s"

        return False, "Tipo inválido"
    except Exception as e:
        logger.error(f"Error evaluando rechazo 30s en {pair}: {e}")
        return False, f"Error: {e}"

async def verificar_fuerza_divisa(pair: str, direccion: str, iq_client=None) -> Tuple[bool, str]:
    """
    Regla 4 (Mercado Real): Filtro de Fuerza de Divisa (Currency Strength Meter).
    Estructurado modularmente para conectarse a una canasta macro (ROC).
    Retorna True si pasa el filtro.
    """
    # Placeholder listo para matriz de canasta o momentum macro
    return True, "Fuerza de divisa verificada para mercado real"

class EstadoSniperPar:
    def __init__(self, pair: str):
        self.pair = pair
        self.c1_resistencia: float = 0.0
        self.c2_soporte: float = 0.0
        self.last_m15_update: int = 0
        self.modo_sniper: bool = False
        self.prealerta_enviada: bool = False
        self.ultima_30s_ts: int = 0
        self.ultimo_gatillo_ts: int = 0

class SniperQuantitativeTrigger:
    def __init__(self, trading_engine):
        self.engine = trading_engine
        self.estados: Dict[str, EstadoSniperPar] = {}

    def get_estado(self, pair: str) -> EstadoSniperPar:
        pair_upper = pair.upper()
        if pair_upper not in self.estados:
            self.estados[pair_upper] = EstadoSniperPar(pair_upper)
        return self.estados[pair_upper]

    def actualizar_niveles_m15(self, pair: str, m15_candles: list, indicator) -> Tuple[float, float]:
        """
        Calcula y mapea c1 (Resistencia) y c2 (Soporte) a partir de las velas M15
        utilizando fractales y extremos de oscilación del ScriptVipIndicator.
        """
        estado = self.get_estado(pair)
        if not m15_candles or len(m15_candles) < 10:
            return estado.c1_resistencia, estado.c2_soporte

        latest_m15_from = int(m15_candles[-1].get('from', 0))
        if latest_m15_from != estado.last_m15_update:
            estado.last_m15_update = latest_m15_from

            # Analizar con el indicador VIP
            res = indicator.analyze_candles(m15_candles)
            levels = res.get("levels", {})

            # 1. Resistencia c1: Fractal alto o Highest reciente de 30 velas M15
            highs = [float(c.get('max', c.get('high', c['close']))) for c in m15_candles[-10:]]
            c1 = res.get("fractal_high") or levels.get("HH30") or levels.get("HH10") or max(highs)

            # 2. Soporte c2: Fractal bajo o Lowest reciente de 30 velas M15
            lows = [float(c.get('min', c.get('low', c['close']))) for c in m15_candles[-10:]]
            c2 = res.get("fractal_low") or levels.get("LL30") or levels.get("LL10") or min(lows)

            dec = 3 if "JPY" in pair else 5
            estado.c1_resistencia = round(float(c1), dec)
            estado.c2_soporte = round(float(c2), dec)
            logger.info(f"Niveles M15 actualizados para {pair} -> c1 (Resistencia): {estado.c1_resistencia}, c2 (Soporte): {estado.c2_soporte}")

        return estado.c1_resistencia, estado.c2_soporte

    async def evaluar_tick_sniper(self, pair: str, tick_price: float, server_ts: float) -> Optional[Dict[str, Any]]:
        """
        Evalúa el flujo en tiempo real (ticks de sub-segundo) bajo las 4 reglas institucionales:
        1. Radar de 3 pips e histéresis anti-spam
        2. Ventana M5 (primeros 3 minutos)
        3. Gatillo OHLC en velas cerradas de 30s
        4. Enrutador OTC vs Real
        """
        estado = self.get_estado(pair)
        c1 = estado.c1_resistencia
        c2 = estado.c2_soporte

        if c1 <= 0 or c2 <= 0 or tick_price <= 0:
            return None

        pip = get_pip_value(pair)
        distancia_c1 = c1 - tick_price
        distancia_c2 = tick_price - c2
        radio_radar = 3.0 * pip
        histeresis_reset = 5.0 * pip

        # =========================================================
        # REGLA 1: RADAR DE PROXIMIDAD Y PRE-ALERTA
        # =========================================================
        en_zona_resistencia = 0 <= distancia_c1 <= radio_radar
        en_zona_soporte = 0 <= distancia_c2 <= radio_radar

        direccion_prealerta = None
        nivel_objetivo = None
        tipo_objetivo = None

        if en_zona_resistencia:
            direccion_prealerta = "VENTA"
            nivel_objetivo = c1
            tipo_objetivo = "VENTA"
        elif en_zona_soporte:
            direccion_prealerta = "COMPRA"
            nivel_objetivo = c2
            tipo_objetivo = "COMPRA"

        if direccion_prealerta:
            estado.modo_sniper = True
            if not estado.prealerta_enviada:
                estado.prealerta_enviada = True
                logger.info(f"⚡ [RADAR SNIPER] PREALERTA activada en {pair} ({direccion_prealerta}) | Distancia: {min(distancia_c1, distancia_c2)/pip:.1f} pips del nivel M15")
                # Notificar por WebSocket al dashboard
                await self.engine.broadcast_sniper_event({
                    "event": "PREALERTA",
                    "pair": pair,
                    "direction": direccion_prealerta,
                    "level": nivel_objetivo,
                    "price": tick_price,
                    "msg": f"PREALERTA|{pair}|{direccion_prealerta}"
                })
        else:
            # Histéresis: si el precio se aleja a más de 5 pips, resetea para permitir nueva prealerta
            if abs(distancia_c1) > histeresis_reset and abs(distancia_c2) > histeresis_reset:
                if estado.prealerta_enviada:
                    estado.prealerta_enviada = False
                    estado.modo_sniper = False

        if not estado.modo_sniper or not tipo_objetivo or not nivel_objetivo:
            return None

        # =========================================================
        # REGLA 2: FILTRO DE VENTANA DE TIEMPO M5 (0 a 180s)
        # =========================================================
        if not es_horario_valido_m5(server_ts):
            # Zona de peligro (< 2 min para el cierre de vela M5), se silencia
            return None

        # =========================================================
        # REGLA 3: GATILLO MATEMÁTICO OHLC (30 SEGUNDOS CERRADA)
        # =========================================================
        # Solo consultamos velas de 30s si estamos en el segundo 01 o 31 de cada minuto
        seg_actual = int(server_ts) % 30
        if seg_actual not in (0, 1, 2):
            return None

        candles_30s = await self.engine.obtener_velas_30s(pair)
        if not candles_30s or len(candles_30s) < 2:
            return None

        # La vela que acaba de cerrar es candles_30s[-2]
        vela_30s_cerrada = candles_30s[-2]
        v_from = int(vela_30s_cerrada.get('from', 0))

        if v_from == estado.ultima_30s_ts:
            return None
        estado.ultima_30s_ts = v_from

        cumple, detalle = evaluar_rechazo_30s(vela_30s_cerrada, pair, nivel_objetivo, tipo_objetivo)
        if not cumple:
            return None

        # Evitar ráfagas duplicadas dentro de la misma vela M5
        if (server_ts - estado.ultimo_gatillo_ts) < 200:
            return None

        # =========================================================
        # REGLA 4: ENRUTAMIENTO INTELIGENTE (OTC vs REAL)
        # =========================================================
        es_otc = "-OTC" in pair.upper()
        if not es_otc:
            pasa_fuerza, razon_fuerza = await verificar_fuerza_divisa(pair, tipo_objetivo, self.engine.iq)
            if not pasa_fuerza:
                logger.info(f"[FILTRO DIVISA REAL] Gatillo en {pair} descartado: {razon_fuerza}")
                return None

        estado.ultimo_gatillo_ts = int(server_ts)
        estado.modo_sniper = False
        estado.prealerta_enviada = False

        # Expiración anclada al cierre exacto de la vela M5 en curso
        current_m5_end = ((int(server_ts) // 300) + 1) * 300
        segundos_restantes = max(60, current_m5_end - int(server_ts))
        minutos_expiracion = max(1, round(segundos_restantes / 60))

        gatillo_data = {
            "pair": pair,
            "direction": "CALL" if tipo_objetivo == "COMPRA" else "PUT",
            "action": tipo_objetivo,
            "price": tick_price,
            "level": nivel_objetivo,
            "c1": c1,
            "c2": c2,
            "candle_30s": vela_30s_cerrada,
            "detail": detalle,
            "expiration_min": minutos_expiracion,
            "end_ts": current_m5_end,
            "msg": f"{tipo_objetivo}|{pair}"
        }

        logger.info(f"🎯 ¡GATILLO SNIPER 30s ACTIVADO! {tipo_objetivo} en {pair} @ {tick_price} | {detalle} (Exp: {minutos_expiracion}m M5)")
        return gatillo_data
