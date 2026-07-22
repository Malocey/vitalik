"""
E-Mail KI-Entscheidungs-Engine für VG Delikatessen.
Analysiert eingehende E-Mail-Inhalte, ordnet Lieferanten zu und klassifiziert die kaufmännische Absicht.
"""

import logging
import re
from typing import Any, Dict, List, Optional
from src.core.contact_memory import contact_memory

logger = logging.getLogger("EmailDecisionEngine")


class EmailDecisionEngine:
    def classify_email(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analysiert Betreff, Absender und Nachrichtentext einer E-Mail.
        """
        subject = email_data.get("subject", "") or ""
        sender = email_data.get("from", "") or email_data.get("sender", "") or ""
        body = email_data.get("body", "") or email_data.get("full_text", "") or ""

        if "from:" in body.lower() and (not sender or sender.endswith(".eml")):
            for line in body.splitlines()[:15]:
                if line.lower().startswith("from:"):
                    sender = line.split(":", 1)[1].strip()
                elif line.lower().startswith("subject:") and (not subject or subject.endswith(".eml") or not subject.strip()):
                    extracted_sub = line.split(":", 1)[1].strip()
                    if extracted_sub:
                        subject = extracted_sub

        combined_text = f"{subject}\n{body}".lower()

        # Supplier Matching via Contact Memory
        matched_contact = contact_memory.match_text(f"{sender} {subject} {body}", role="supplier")
        supplier_name = matched_contact["name"] if matched_contact else self._extract_sender_name(sender)

        # Intent Classification via Rules & Pattern Matching
        intent = "ALLGEMEINE_ANFRAGE"
        action = "Klassische Rückfrage vorbereiten"

        if any(w in combined_text for w in ["rechnung", "monatsrechnung", "invoice", "gutschrift"]):
            intent = "RECHNUNG_INVOICE"
            action = "Rechnungseingang bestätigen & Belege verarbeiten"
        elif any(w in combined_text for w in ["preiserhöhung", "preisbildung", "preisanpassung", "teuer", "preiserhoehung"]):
            intent = "PREIS_ERHOEHUNG"
            action = "Preiserhöhung prüfen & höflichen Einwand entwerfen"
        elif any(w in combined_text for w in ["lieferschein", "lieferung", "wareneingang", "fehlmenge"]):
            intent = "LIEFERSCHEIN_DISCREPANCY"
            action = "Lieferschein mit Bestellung abgleichen & Status anfragen"
        elif any(w in combined_text for w in ["mahnung", "zahlungserinnerung", "fällig", "faellig"]):
            intent = "MAHNUNG_ZAHLUNGSERINNERUNG"
            action = "Zahlungsstatus in FTS5/sevDesk prüfen & Rückmeldung verfassen"

        return {
            "supplier_name": supplier_name,
            "sender_email": sender,
            "subject": subject,
            "intent": intent,
            "suggested_action": action,
            "matched_contact": matched_contact
        }

    def _extract_sender_name(self, sender: str) -> str:
        if "<" in sender and ">" in sender:
            name_part = sender.split("<")[0].strip('" ').strip("' ")
            if name_part:
                return name_part
        if "@" in sender:
            domain = sender.split("@")[-1].split(".")[0].capitalize()
            return domain
        return sender or "Unbekannter Lieferant"


email_decision_engine = EmailDecisionEngine()
