"""
Matching Engine für VG Delikatessen.
Gleicht Lieferscheine und Eingangsrechnungen desselben Lieferanten ab und erkennt Abweichungen.
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from config import DATA_DIR

logger = logging.getLogger("MatchingEngine")


class MatchingEngine:
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
                CREATE TABLE IF NOT EXISTS beleg_matches (
                    match_id TEXT PRIMARY KEY,
                    invoice_id TEXT,
                    delivery_note_id TEXT,
                    supplier_name TEXT,
                    match_status TEXT NOT NULL,
                    confidence_score REAL NOT NULL,
                    discrepancies_json TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

    def match_invoice_with_delivery_note(
        self,
        invoice: Dict[str, Any],
        delivery_note: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Gleicht eine Rechnung mit einem Lieferschein ab.
        """
        inv_id = invoice.get("beleg_id") or invoice.get("rechnungsnummer") or "UNBEKANNT"
        inv_supplier = (invoice.get("lieferant") or "").strip().lower()
        inv_brutto = float(invoice.get("brutto") or 0.0)

        if not delivery_note:
            match_res = {
                "match_id": f"match_{inv_id}",
                "invoice_id": inv_id,
                "delivery_note_id": None,
                "supplier_name": invoice.get("lieferant", "Unbekannt"),
                "match_status": "OFFEN_KEIN_LIEFERSCHEIN",
                "confidence_score": 0.5,
                "discrepancies": ["Kein zugehöriger Lieferschein im System gefunden."]
            }
            self._save_match(match_res)
            return match_res

        dn_id = delivery_note.get("beleg_id") or delivery_note.get("rechnungsnummer") or "LS_UNBEKANNT"
        dn_supplier = (delivery_note.get("lieferant") or "").strip().lower()
        dn_brutto = float(delivery_note.get("brutto") or 0.0)

        discrepancies = []
        if inv_supplier and dn_supplier and inv_supplier != dn_supplier:
            discrepancies.append(f"Lieferant weicht ab: '{invoice.get('lieferant')}' vs '{delivery_note.get('lieferant')}'")

        if dn_brutto > 0.0 and inv_brutto > 0.0 and abs(dn_brutto - inv_brutto) > 0.05:
            discrepancies.append(f"Betrag weicht ab: Rechnung {inv_brutto:.2f}€ vs Lieferschein {dn_brutto:.2f}€")

        status = "MATCHED" if not discrepancies else "DISCREPANCY"
        confidence = 0.95 if status == "MATCHED" else 0.70

        match_res = {
            "match_id": f"match_{inv_id}_{dn_id}",
            "invoice_id": inv_id,
            "delivery_note_id": dn_id,
            "supplier_name": invoice.get("lieferant", "Unbekannt"),
            "match_status": status,
            "confidence_score": confidence,
            "discrepancies": discrepancies
        }
        self._save_match(match_res)
        return match_res

    def _save_match(self, match_res: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO beleg_matches (
                    match_id, invoice_id, delivery_note_id, supplier_name,
                    match_status, confidence_score, discrepancies_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                match_res["match_id"],
                match_res["invoice_id"],
                match_res.get("delivery_note_id"),
                match_res["supplier_name"],
                match_res["match_status"],
                match_res["confidence_score"],
                json.dumps(match_res.get("discrepancies", []))
            ))
            conn.commit()

    def get_all_matches(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM beleg_matches ORDER BY updated_at DESC LIMIT ?
            """, (limit,)).fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["discrepancies"] = json.loads(item.get("discrepancies_json") or "[]")
                result.append(item)
            return result


matching_engine = MatchingEngine()
