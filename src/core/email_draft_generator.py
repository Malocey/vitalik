"""
E-Mail KI-Antwort-Entwurfs-Generator für VG Delikatessen.
Erstellt professionelle E-Mail-Antwortentwürfe in Vitalis Tonalität und speichert sie zur Dashboard-Vorschau.
"""

import json
import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from config import DATA_DIR

logger = logging.getLogger("EmailDraftGenerator")


class EmailDraftGenerator:
    def __init__(self, db_path: Path = DATA_DIR / "rag_index.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS email_drafts (
                    draft_id TEXT PRIMARY KEY,
                    original_subject TEXT,
                    sender_email TEXT,
                    supplier_name TEXT,
                    intent TEXT NOT NULL,
                    suggested_action TEXT,
                    generated_draft TEXT NOT NULL,
                    status TEXT DEFAULT 'PENDING_APPROVAL',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

    def generate_draft(self, email_data: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
        supplier = classification.get("supplier_name", "Lieferant")
        subject = classification.get("subject", "Anfrage")
        sender = classification.get("sender_email", "")
        intent = classification.get("intent", "ALLGEMEINE_ANFRAGE")
        action = classification.get("suggested_action", "")

        greeting = f"Servus {supplier}-Team,"
        farewell = "Beste Grüße aus der Feinkostküche,\nVitali\nVG Delikatessen"

        if intent == "PREIS_ERHOEHUNG":
            body = (
                f"{greeting}\n\n"
                f"vielen Dank für Ihre E-Mail bzgl. der angekündigten Preisanpassung.\n"
                f"Als langjähriger Partner von VG Delikatessen lege ich großen Wert auf faire und verlässliche Preise. "
                f"Gibt es bei den aktuellen Rohstoffpreisen Spielraum, die Anpassung für unsere nächsten Bestellungen auszusetzen oder abzufedern?\n\n"
                f"Ich freue mich auf Ihre Rückmeldung.\n\n{farewell}"
            )
        elif intent == "RECHNUNG_INVOICE":
            body = (
                f"{greeting}\n\n"
                f"vielen Dank für die Zusendung der Belege ('{subject}').\n"
                f"Wir prüfen die Unterlagen intern. Dieser Entwurf bestätigt weder die sachliche Prüfung noch eine Zahlungsfreigabe.\n\n"
                f"{farewell}"
            )
        elif intent == "LIEFERSCHEIN_DISCREPANCY":
            body = (
                f"{greeting}\n\n"
                f"bezugnehmend auf Ihre E-Mail bzgl. Lieferschein/Lieferung prüfen wir aktuell den Wareneingang bei uns vor Ort.\n"
                f"Sobald der Vollständigkeitsabgleich abgeschlossen ist, geben wir Ihnen umgehend Bescheid.\n\n"
                f"{farewell}"
            )
        elif intent == "MAHNUNG_ZAHLUNGSERINNERUNG":
            body = (
                f"{greeting}\n\n"
                f"vielen Dank für Ihren Hinweis. Wir prüfen den Vorgang und den Zahlungsstatus intern.\n"
                f"Anschließend melden wir uns mit einer belastbaren Rückmeldung.\n\n"
                f"{farewell}"
            )
        else:
            body = (
                f"{greeting}\n\n"
                f"vielen Dank für Ihre E-Mail zu '{subject}'.\n"
                f"Wir haben Ihre Nachricht erhalten und kommen in Kürze mit einer Rückmeldung auf Sie zu.\n\n"
                f"{farewell}"
            )

        stable_key = "\x1f".join((subject, sender, intent)).encode("utf-8")
        draft_id = f"draft_{hashlib.sha256(stable_key).hexdigest()[:24]}"
        draft_res = {
            "draft_id": draft_id,
            "original_subject": subject,
            "sender_email": sender,
            "supplier_name": supplier,
            "intent": intent,
            "suggested_action": action,
            "generated_draft": body,
            "status": "PENDING_APPROVAL"
        }

        self._save_draft(draft_res)
        return draft_res

    def _save_draft(self, draft: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO email_drafts (
                    draft_id, original_subject, sender_email, supplier_name,
                    intent, suggested_action, generated_draft, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                draft["draft_id"],
                draft["original_subject"],
                draft["sender_email"],
                draft["supplier_name"],
                draft["intent"],
                draft["suggested_action"],
                draft["generated_draft"],
                draft["status"]
            ))
            conn.commit()

    def get_pending_drafts(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM email_drafts ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]


email_draft_generator = EmailDraftGenerator()
