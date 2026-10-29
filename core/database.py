"""
Módulo de Base de Datos SQLite Persistente (trading.db)
Garantiza que el historial de operaciones, señales y estadísticas
se guarden de forma permanente y NUNCA se borren ni se sobreescriban al reiniciar.
"""

import sqlite3
import os
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "trading.db")

class DatabaseManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        d = os.path.dirname(self.db_path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Crea las tablas únicamente si no existen. NUNCA borra ni altera datos existentes."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        order_id TEXT,
                        pair TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        result TEXT NOT NULL,
                        profit REAL NOT NULL,
                        amount REAL NOT NULL,
                        entry_price REAL,
                        close_price REAL,
                        entry_time TEXT,
                        close_time TEXT,
                        martingale_step INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS signals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        pair TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        strategy TEXT DEFAULT 'VIP_OSCILLATOR',
                        timeframe INTEGER DEFAULT 60,
                        status TEXT DEFAULT 'CONFIRMED',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
                logger.info("Base de datos SQLite verificada y lista (tablas preservadas).")
        except Exception as e:
            logger.error(f"Error inicializando base de datos SQLite: {e}")

    def save_trade(self, trade: Dict[str, Any]):
        """Inserta una nueva operación en la base de datos sin tocar las anteriores."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO trades (
                        order_id, pair, direction, result, profit, amount,
                        entry_price, close_price, entry_time, close_time, martingale_step
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(trade.get("id", "")),
                    trade.get("pair", ""),
                    trade.get("direction", ""),
                    trade.get("result", ""),
                    float(trade.get("profit", 0.0)),
                    float(trade.get("amount", 0.0)),
                    float(trade.get("entry_price", 0.0)),
                    float(trade.get("close_price", 0.0)),
                    trade.get("entry_time", ""),
                    trade.get("close_time", ""),
                    int(trade.get("martingale_step", 0))
                ))
                conn.commit()
                logger.info(f"Operación guardada en SQLite DB: {trade.get('pair')} {trade.get('result')}")
        except Exception as e:
            logger.error(f"Error guardando trade en SQLite DB: {e}")

    def load_trades(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Carga el historial existente de la base de datos ordenado cronológicamente."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT order_id as id, pair, direction, result, profit, amount,
                           entry_price, close_price, entry_time, close_time, martingale_step
                    FROM trades
                    ORDER BY id ASC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error cargando trades de SQLite DB: {e}")
            return []

    def get_trades_paginated(self, page: int = 1, limit: int = 10) -> Dict[str, Any]:
        """Obtiene las operaciones paginadas en orden descendente (más recientes primero)."""
        try:
            page = max(1, int(page))
            limit = max(1, min(100, int(limit)))
            offset = (page - 1) * limit
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as total FROM trades")
                total = cursor.fetchone()["total"] or 0

                cursor.execute("""
                    SELECT id, order_id, pair, direction, result, profit, amount,
                           entry_price, close_price, entry_time, close_time, martingale_step, created_at
                    FROM trades
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
                rows = cursor.fetchall()
                trades = []
                for r in rows:
                    d = dict(r)
                    m_step = d.get("martingale_step", 0)
                    if m_step == 1:
                        d["entry_label"] = "E1 Apertura"
                    elif m_step == 2:
                        d["entry_label"] = "E2 Retroceso"
                    else:
                        d["entry_label"] = "Entrada M5"
                    trades.append(d)

                total_pages = max(1, (total + limit - 1) // limit)
                return {
                    "trades": trades,
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "total_pages": total_pages
                }
        except Exception as e:
            logger.error(f"Error obteniendo trades paginados: {e}")
            return {"trades": [], "total": 0, "page": 1, "limit": limit, "total_pages": 1}

    def get_stats(self) -> Dict[str, Any]:
        """Calcula estadísticas históricas acumuladas desde la base de datos."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) as wins,
                        SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) as losses,
                        SUM(CASE WHEN result NOT IN ('WIN', 'LOSS') THEN 1 ELSE 0 END) as equals,
                        SUM(profit) as net_profit
                    FROM trades
                """)
                row = cursor.fetchone()
                total = row["total"] or 0
                wins = row["wins"] or 0
                losses = row["losses"] or 0
                equals = row["equals"] or 0
                net_profit = round(row["net_profit"] or 0.0, 2)
                winrate = round((wins / (wins + losses) * 100), 1) if (wins + losses) > 0 else 0.0
                return {
                    "total_trades": total,
                    "wins": wins,
                    "losses": losses,
                    "equals": equals,
                    "net_profit": net_profit,
                    "winrate": winrate
                }
        except Exception as e:
            logger.error(f"Error calculando stats de SQLite DB: {e}")
            return {"total_trades": 0, "wins": 0, "losses": 0, "equals": 0, "net_profit": 0.0, "winrate": 0.0}
