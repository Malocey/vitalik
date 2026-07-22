"""
Lieferanten-Preisentwicklungs & Inflations-Monitor für VG Delikatessen.
Erfasst Artikel-Einzelpreise aus Rechnungen, Excel-Preislisten und Angeboten und berechnet Preistrends.
"""

import logging
import sqlite3
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from config import DATA_DIR

logger = logging.getLogger("PriceMonitor")


class PriceMonitor:
    def __init__(self, db_path: Path = DATA_DIR / "rag_index.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS item_price_history (
                    price_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    supplier_name TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    unit_price REAL NOT NULL,
                    unit_name TEXT DEFAULT 'Stück',
                    document_id TEXT,
                    source_file TEXT,
                    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_supplier_item
                ON item_price_history(supplier_name, item_name);
            """)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_price_document_item
                ON item_price_history(document_id, supplier_name, item_name, unit_name)
                WHERE document_id IS NOT NULL AND document_id != '';
            """)
            conn.commit()

    def record_price(
        self,
        supplier_name: str,
        item_name: str,
        unit_price: float,
        unit_name: str = "Stück",
        document_id: str = "",
        source_file: str = ""
    ) -> bool:
        if not supplier_name or not item_name or unit_price <= 0.0:
            return False
        supplier_name = self._normalize_label(supplier_name)
        item_name = self._normalize_label(item_name)
        unit_name = self._normalize_unit(unit_name)
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO item_price_history (
                    supplier_name, item_name, unit_price, unit_name, document_id, source_file, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(document_id, supplier_name, item_name, unit_name)
                WHERE document_id IS NOT NULL AND document_id != ''
                DO UPDATE SET unit_price=excluded.unit_price, source_file=excluded.source_file
            """, (supplier_name.strip(), item_name.strip(), float(unit_price), unit_name, document_id, source_file))
            conn.commit()
            return True

    @staticmethod
    def _normalize_label(value: str) -> str:
        return " ".join(str(value).strip().split())

    @staticmethod
    def _normalize_unit(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]", "", str(value or "").casefold())
        aliases = {
            "kilogramm": "kg", "kilo": "kg", "kg": "kg",
            "gramm": "g", "gr": "g", "g": "g",
            "stuck": "Stück", "stueck": "Stück", "stk": "Stück",
            "karton": "Karton", "kt": "Karton", "liter": "l", "l": "l",
        }
        return aliases.get(normalized, str(value or "Stück").strip())

    def get_price_trends(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT supplier_name, item_name, unit_price, unit_name, recorded_at
                FROM item_price_history
                ORDER BY supplier_name, item_name, recorded_at ASC
            """).fetchall()

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            key = f"{r['supplier_name']}|||{r['item_name']}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(dict(r))

        trends = []
        for key, price_list in grouped.items():
            supplier, item = key.split("|||")
            oldest = price_list[0]["unit_price"]
            latest = price_list[-1]["unit_price"]
            diff_pct = round(((latest - oldest) / oldest) * 100.0, 2) if oldest > 0 else 0.0

            warning = "PREISERHOEHUNG_WARNUNG" if diff_pct > 2.0 else "NORMAL"
            trends.append({
                "supplier_name": supplier,
                "item_name": item,
                "unit_name": price_list[-1]["unit_name"],
                "oldest_price": oldest,
                "latest_price": latest,
                "change_pct": diff_pct,
                "status": warning,
                "data_points": len(price_list)
            })

        return sorted(trends, key=lambda x: x["change_pct"], reverse=True)


price_monitor = PriceMonitor()
