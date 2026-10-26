"""
Motor de Cálculo del Indicador 'SCRIPT VIP' (Lua a Python)
Implementa:
- SMA Fast (periodo 1) y SMA Slow (periodo 34)
- Buffer 1: Oscilador (smaFast - smaSlow)
- Buffer 2: WMA (Weighted Moving Average) con periodo Signal (5)
- Cruce de Compra (CALL): buffer1 cruza hacia arriba buffer2
- Cruce de Venta (PUT): buffer1 cruza hacia abajo buffer2
- Detección de Fractales (Máximos y Mínimos en ventana de 5 velas)
- Niveles clave Highest / Lowest (10, 30, 60, 100, 150, 200)
"""

import numpy as np
from typing import List, Dict, Optional, Tuple

class ScriptVipIndicator:
    def __init__(self, fast_period: int = 1, slow_period: int = 34, signal_period: int = 5):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    @staticmethod
    def calculate_sma(series: np.ndarray, period: int) -> np.ndarray:
        if len(series) < period:
            return np.full_like(series, fill_value=np.nan)
        weights = np.ones(period) / period
        sma = np.convolve(series, weights, mode='valid')
        # Rellenar los primeros period - 1 con NaN para preservar longitud
        pad = np.full(period - 1, np.nan)
        return np.concatenate((pad, sma))

    @staticmethod
    def calculate_wma(series: np.ndarray, period: int) -> np.ndarray:
        if len(series) < period:
            return np.full_like(series, fill_value=np.nan)
        weights = np.arange(1, period + 1)
        w_sum = weights.sum()
        wma = np.convolve(series, weights[::-1] / w_sum, mode='valid')
        pad = np.full(period - 1, np.nan)
        return np.concatenate((pad, wma))

    def analyze_candles(self, candles: List[Dict]) -> Dict:
        """
        candles: lista de velas en orden cronológico (de la más vieja a la más reciente).
        Cada vela contiene: {'id': ..., 'from': ..., 'to': ..., 'open': ..., 'close': ..., 'min': ..., 'max': ..., 'volume': ...}
        """
        min_required = max(self.slow_period + self.signal_period + 5, 50)
        if len(candles) < min_required:
            return {
                "signal": None,
                "reason": f"Velas insuficientes ({len(candles)}/{min_required})",
                "buffer1": 0.0,
                "buffer2": 0.0,
                "prev_buffer1": 0.0,
                "prev_buffer2": 0.0,
                "fractal_high": None,
                "fractal_low": None,
                "levels": {}
            }

        closes = np.array([float(c['close']) for c in candles], dtype=np.float64)
        highs = np.array([float(c.get('max', c.get('high', c['close']))) for c in candles], dtype=np.float64)
        lows = np.array([float(c.get('min', c.get('low', c['close']))) for c in candles], dtype=np.float64)

        # 1. smaFast (periodo 1 es igual al close)
        sma_fast = closes if self.fast_period == 1 else self.calculate_sma(closes, self.fast_period)
        
        # 2. smaSlow (periodo 34)
        sma_slow = self.calculate_sma(closes, self.slow_period)

        # 3. buffer1 = smaFast - smaSlow
        buffer1 = sma_fast - sma_slow

        # 4. buffer2 = WMA(buffer1, Signal_period=5)
        # Tomamos la porción válida de buffer1 para el WMA
        valid_idx = self.slow_period - 1
        valid_b1 = buffer1[valid_idx:]
        wma_valid = self.calculate_wma(valid_b1, self.signal_period)
        buffer2 = np.full_like(buffer1, np.nan)
        buffer2[valid_idx:] = wma_valid

        # Tomamos los últimos 2 valores cerrados (índice -1 para la última vela cerrada, -2 para la anterior)
        curr_b1 = buffer1[-1]
        curr_b2 = buffer2[-1]
        prev_b1 = buffer1[-2]
        prev_b2 = buffer2[-2]

        signal = None
        # Condición de compra (CALL):
        # buffer1 > buffer2 and buffer1[1] < buffer2[1]
        if curr_b1 > curr_b2 and prev_b1 <= prev_b2:
            signal = "CALL"
        # Condición de venta (PUT):
        # buffer1 < buffer2 and buffer1[1] > buffer2[1]
        elif curr_b1 < curr_b2 and prev_b1 >= prev_b2:
            signal = "PUT"

        # 5. Fractales High/Low (5 velas con la vela central como extremo)
        # Lua: c = high[2]; high<=c and high[1]<=c and high[3]<=c and high[4]<=c
        # En orden cronológico: si índice -3 es la vela central (high[-3]),
        # comparada con highs[-1], highs[-2], highs[-4], highs[-5]
        fractal_high = None
        fractal_low = None
        if len(highs) >= 5:
            c_high = highs[-3]
            if (highs[-1] <= c_high and highs[-2] <= c_high and 
                highs[-4] <= c_high and highs[-5] <= c_high):
                fractal_high = float(c_high)

            c_low = lows[-3]
            if (lows[-1] >= c_low and lows[-2] >= c_low and 
                lows[-4] >= c_low and lows[-5] >= c_low):
                fractal_low = float(c_low)

        # 6. Niveles de soporte y resistencia (10, 30, 60, 100, 150, 200)
        levels = {}
        for p in [10, 30, 60, 100, 150, 200]:
            if len(highs) > p:
                levels[f"HH{p}"] = float(np.max(highs[-p-1:-1]))
                levels[f"LL{p}"] = float(np.min(lows[-p-1:-1]))

        return {
            "signal": signal,
            "buffer1": float(curr_b1),
            "buffer2": float(curr_b2),
            "prev_buffer1": float(prev_b1),
            "prev_buffer2": float(prev_b2),
            "fractal_high": fractal_high,
            "fractal_low": fractal_low,
            "levels": levels,
            "last_close": float(closes[-1]),
            "last_open": float(candles[-1]['open']),
            "last_high": float(highs[-1]),
            "last_low": float(lows[-1]),
            "last_candle_from": candles[-1].get('from', 0)
        }
