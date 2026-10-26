"""
Gestor de Licencias MT5 y Validación de Clientes
Almacena en SQLite las claves de licencia, nombres de clientes, cuentas MT5 permitidas,
fechas de expiración y estado de activación.
"""

import os
import sqlite3
import secrets
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mt5_licenses.db")

class LicenseManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Crea la tabla de licencias si no existe."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mt5_licenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    license_key TEXT UNIQUE NOT NULL,
                    client_name TEXT NOT NULL,
                    account_mt5 TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT DEFAULT 'ACTIVA',
                    notes TEXT DEFAULT '',
                    last_ip TEXT DEFAULT '',
                    last_used_at TEXT DEFAULT ''
                )
            """)
            conn.commit()

        # Si no hay ninguna licencia, crear una licencia Master/Demo por defecto
        if not self.list_licenses():
            self.create_license(
                client_name="Admin Master / Ouyang",
                account_mt5="", # Cualquier cuenta
                days_valid=365,
                notes="Licencia Principal de Administrador",
                custom_key="VIP-MASTER-2026-KEY"
            )

    def generate_key(self) -> str:
        """Genera una clave estilizada: VIP-XXXX-XXXX-XXXX"""
        part1 = secrets.token_hex(2).upper()
        part2 = secrets.token_hex(2).upper()
        part3 = secrets.token_hex(2).upper()
        return f"VIP-{part1}-{part2}-{part3}"

    def create_license(
        self,
        client_name: str,
        account_mt5: str = "",
        days_valid: int = 30,
        notes: str = "",
        custom_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Crea una nueva licencia con validez en días."""
        key = custom_key.strip().upper() if custom_key else self.generate_key()
        now = datetime.now()
        expires = now + timedelta(days=days_valid)

        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        exp_str = expires.strftime("%Y-%m-%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO mt5_licenses (license_key, client_name, account_mt5, created_at, expires_at, status, notes)
                VALUES (?, ?, ?, ?, ?, 'ACTIVA', ?)
            """, (key, client_name.strip(), account_mt5.strip(), now_str, exp_str, notes.strip()))
            conn.commit()
            new_id = cursor.lastrowid

        logger.info(f"Licencia MT5 creada: {key} para {client_name} (Expira: {exp_str})")
        return {
            "id": new_id,
            "license_key": key,
            "client_name": client_name,
            "account_mt5": account_mt5,
            "created_at": now_str,
            "expires_at": exp_str,
            "status": "ACTIVA"
        }

    def validate_license(self, license_key: str, account_number: str = "", ip: str = "") -> Tuple[bool, str, Dict[str, Any]]:
        """
        Valida si una licencia existe, está activa y no ha vencido.
        Retorna (es_valida, mensaje, data_dict)
        """
        key_clean = license_key.strip().upper()
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mt5_licenses WHERE license_key = ?", (key_clean,))
            row = cursor.fetchone()

            if not row:
                return False, "Licencia inexistente o incorrecta.", {}

            lic = dict(row)

            # Verificar estado
            if lic["status"].upper() != "ACTIVA":
                return False, f"La licencia se encuentra {lic['status']}. Contacta al administrador.", lic

            # Verificar expiración
            exp_dt = datetime.strptime(lic["expires_at"], "%Y-%m-%d %H:%M:%S")
            if now_dt > exp_dt:
                # Marcar como expirada
                cursor.execute("UPDATE mt5_licenses SET status = 'EXPIRADA' WHERE id = ?", (lic["id"],))
                conn.commit()
                return False, f"Tu licencia expiró el {lic['expires_at']}.", lic

            # Verificar cuenta MT5 si está configurada
            allowed_acc = lic["account_mt5"].strip()
            if allowed_acc and account_number.strip():
                if allowed_acc != account_number.strip():
                    return False, f"Esta licencia está vinculada a la cuenta MT5: {allowed_acc}.", lic
            elif not allowed_acc and account_number.strip():
                # Si no estaba vinculada y es su primer uso, la vinculamos automáticamente
                cursor.execute("UPDATE mt5_licenses SET account_mt5 = ? WHERE id = ?", (account_number.strip(), lic["id"]))
                lic["account_mt5"] = account_number.strip()

            # Registrar último uso e IP
            cursor.execute("UPDATE mt5_licenses SET last_ip = ?, last_used_at = ? WHERE id = ?", (ip, now_str, lic["id"]))
            conn.commit()

            days_left = (exp_dt - now_dt).days
            msg = f"Licencia válida para {lic['client_name']}. Días restantes: {max(0, days_left)}."
            return True, msg, lic

    def list_licenses(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mt5_licenses ORDER BY id DESC")
            return [dict(r) for r in cursor.fetchall()]

    def toggle_status(self, license_id: int) -> Tuple[bool, str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM mt5_licenses WHERE id = ?", (license_id,))
            row = cursor.fetchone()
            if not row:
                return False, "Licencia no encontrada"
            cur_st = row["status"]
            new_st = "SUSPENDIDA" if cur_st == "ACTIVA" else "ACTIVA"
            cursor.execute("UPDATE mt5_licenses SET status = ? WHERE id = ?", (new_st, license_id))
            conn.commit()
            return True, new_st

    def delete_license(self, license_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM mt5_licenses WHERE id = ?", (license_id,))
            conn.commit()
            return cursor.rowcount > 0

    def extend_license(self, license_id: int, days: int = 30) -> Tuple[bool, str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT expires_at FROM mt5_licenses WHERE id = ?", (license_id,))
            row = cursor.fetchone()
            if not row:
                return False, "Licencia no encontrada"
            
            cur_exp = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
            base_date = max(datetime.now(), cur_exp)
            new_exp = base_date + timedelta(days=days)
            new_exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("UPDATE mt5_licenses SET expires_at = ?, status = 'ACTIVA' WHERE id = ?", (new_exp_str, license_id))
            conn.commit()
            return True, new_exp_str
