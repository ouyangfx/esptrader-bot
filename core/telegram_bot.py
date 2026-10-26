"""
Gestor de Notificaciones y Comandos de Telegram
Utiliza Bot Token: 8548283354:AAEn6xmBRFOn-pwRxT3pSYClbVQerzrKqAM
Canal: @traderfxapp
Admin: ouyangfx
"""

import requests
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, admin_user: str = "ouyangfx"):
        self.token = token
        self.chat_id = chat_id
        self.admin_user = admin_user
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Envía un mensaje formateado al canal o chat ID configurado."""
        if not self.token or not self.chat_id:
            logger.warning("Telegram Bot Token o Chat ID no configurados.")
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        try:
            resp = requests.post(url, json=payload, timeout=6)
            if resp.status_code == 200:
                return True
            else:
                logger.error(f"Error Telegram {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Excepción enviando mensaje Telegram: {e}")
            return False

    def notify_pre_signal(self, pair: str, direction: str, timeframe_str: str, candle_time: str):
        """Notificación cuando el script detecta la condición (Palabra 'SEÑAL')"""
        icon = "🟢" if direction == "CALL" else "🔴"
        action = "COMPRA / CALL" if direction == "CALL" else "VENTA / PUT"
        msg = (
            f"⚡ <b>¡ALERTA DE SEÑAL DETECTADA!</b> ⚡\n\n"
            f"📊 <b>Par:</b> <code>{pair}</code>\n"
            f"📈 <b>Dirección:</b> {icon} <b>{action}</b>\n"
            f"⏱ <b>Timeframe:</b> {timeframe_str} (Vela de Señal)\n"
            f"🕐 <b>Hora Señal:</b> <code>{candle_time}</code>\n\n"
            f"⏳ <b>Estado:</b> <i>Esperando vela de confirmación a favor...</i>\n"
            f"📏 <i>Al confirmar, trazaremos Fibonacci (50% y 61.8%) uniendo las mechas de ambas velas.</i>\n\n"
            f"🤖 <b>Canal Oficial:</b> @traderfxapp | Admin: @{self.admin_user}"
        )
        return self.send_message(msg)

    def notify_confirmation_failed(self, pair: str, direction: str, reason: str):
        """Notificación cuando la siguiente vela no fue a favor"""
        msg = (
            f"🚫 <b>SEÑAL DESCARTADA / CANCELADA</b> 🚫\n\n"
            f"📊 <b>Par:</b> <code>{pair}</code> ({direction})\n"
            f"❌ <b>Motivo:</b> {reason} (la vela no confirmó el movimiento).\n"
            f"🛡 <b>Protección de capital:</b> Operación evitada.\n\n"
            f"📡 <i>Continuando escaneo del mercado...</i>"
        )
        return self.send_message(msg)

    def notify_entry(self, pair: str, direction: str, entry_time: str, entry_price: float, expiration: int = 5, amount: float = 0.0,
                     fibo_50: float = None, fibo_618: float = None, expire_time: str = None):
        """Notificación en el segundo 00 al ejecutar la operación confirmada con niveles de retroceso Fibo"""
        icon = "🟢 COMPRA (CALL)" if direction == "CALL" else "🔴 VENTA (PUT)"

        fibo_section = ""
        if fibo_50 is not None and fibo_618 is not None:
            fibo_section = (
                f"\n🎯 <b>ZONA DE RETROCESO FIBONACCI (Sniper Entry):</b>\n"
                f"• Fibo 50.0%: <code>{fibo_50:.5f}</code>\n"
                f"• Fibo 61.8%: <code>{fibo_618:.5f}</code>\n"
                f"💡 <i>Tip Pro: Esperar retroceso a la zona 50% - 61.8% para entrar con mejor precio y ventaja.</i>\n"
            )

        exp_line = f"<b>{expiration} Minutos (M5)</b>"
        if expire_time:
            exp_line += f" (🏁 Cierre: <code>{expire_time}</code>)"

        msg = (
            f"🚀 <b>¡OPERACIÓN CONFIRMADA - ENTRADA M5!</b> 🚀\n\n"
            f"📊 <b>Activo:</b> <code>{pair}</code>\n"
            f"🎯 <b>Acción:</b> <b>{icon}</b>\n"
            f"⏰ <b>Hora Entrada:</b> <code>{entry_time}</code> (Apertura Vela)\n"
            f"⏳ <b>Expiración:</b> {exp_line}\n"
            f"💵 <b>Precio Apertura:</b> <code>{entry_price:.5f}</code>\n"
            f"💰 <b>Importe Fijo:</b> <code>${amount:.2f}</code> (Sin Martingala)\n"
            f"{fibo_section}\n"
            f"⚠️ <b>Regla de Oro:</b> La expiración SIEMPRE es al término de la vela de 5M (<code>{expire_time or 'al cierre de vela'}</code>).\n\n"
            f"🤖 <b>Trader 4 Less</b> | @traderfxapp"
        )
        return self.send_message(msg)

    def notify_result(self, pair: str, direction: str, result: str, entry_time: str, close_time: str, 
                      entry_price: float, close_price: float, profit: float, stats: dict = None):
        """Notificación al finalizar el minuto con el resultado y hora de cierre"""
        if result == "WIN":
            status_text = "✅ <b>¡OPERACIÓN GANADA (ITM)!</b> 🎯🎉"
            p_text = f"+${profit:.2f}"
        elif result == "LOSS":
            status_text = "❌ <b>OPERACIÓN PERDIDA (OTM)</b> 📉"
            p_text = f"-${abs(profit):.2f}"
        elif result in ("EQUAL", "DOJI"):
            status_text = "⚪ <b>OPERACIÓN EMPATADA (DOJI)</b> ⚖️"
            p_text = "$0.00"
        else:
            status_text = f"ℹ️ <b>RESULTADO: {result}</b>"
            p_text = f"${profit:.2f}"

        stats_str = ""
        if stats:
            wins = stats.get('wins', 0)
            losses = stats.get('losses', 0)
            total = wins + losses
            wr = (wins / total * 100) if total > 0 else 0
            stats_str = (
                f"\n📊 <b>Estadísticas de Sesión:</b>\n"
                f"• ITM: {wins} | OTM: {losses} | Ratio: {wr:.1f}%\n"
                f"• Balance Sesión: <b>{'+' if stats.get('net_profit', 0) >= 0 else ''}${stats.get('net_profit', 0):.2f}</b>\n"
            )

        msg = (
            f"{status_text}\n\n"
            f"📊 <b>Par:</b> <code>{pair}</code> | <b>Tipo:</b> {direction}\n"
            f"⏰ <b>Hora Entrada:</b> {entry_time}\n"
            f"🏁 <b>Hora Cierre:</b> <code>{close_time}</code>\n"
            f"📈 <b>Precio Apertura:</b> {entry_price:.5f}\n"
            f"📉 <b>Precio Cierre:</b> {close_price:.5f}\n"
            f"💵 <b>Resultado:</b> <b>{p_text}</b>\n"
            f"{stats_str}\n"
            f"🌐 <a href='https://trader4less.com'>Trader 4 Less</a> | @traderfxapp"
        )
        return self.send_message(msg)

    def notify_bot_status(self, is_running: bool, pair: str, account_type: str, balance: float):
        """Notificación de encendido/apagado del bot"""
        state = "🟢 <b>BOT INICIADO Y EN LÍNEA</b>" if is_running else "🔴 <b>BOT DETENIDO</b>"
        msg = (
            f"{state}\n\n"
            f"💼 <b>Cuenta:</b> {account_type}\n"
            f"💰 <b>Saldo:</b> ${balance:.2f}\n"
            f"📊 <b>Pares Activos:</b> <code>{pair}</code>\n"
            f"⏱ <b>Estrategia:</b> SCRIPT VIP (Velas 5M - Sin Martingala)\n"
            f"⏳ <b>Expiración:</b> 5 Minutos (M5)\n"
            f"👤 <b>Admin:</b> @{self.admin_user}\n"
            f"📢 <b>Canal:</b> @traderfxapp"
        )
        return self.send_message(msg)
