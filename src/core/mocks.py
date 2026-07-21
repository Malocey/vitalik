"""
Mock-Module für Google Drive, Telegram und sevDesk.
Ermöglicht vollumfängliche lokale Tests des Betriebssystems ohne aktive Online-Accounts oder Token.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
from config import MOCK_DRIVE_DIR, MOCK_SEVDESK_FILE
from src.core.persona_style import persona_engine

logger = logging.getLogger("Mocks")


class MockGoogleDrive:
    def __init__(self, base_dir: Path = MOCK_DRIVE_DIR):
        self.base_dir = base_dir
        self.manual_review_dir = self.base_dir / "00_Manuelle_Prüfung_Nötig"
        self.manual_review_dir.mkdir(parents=True, exist_ok=True)

    def save_beleg(self, pdf_bytes: bytes, doc_data: Dict[str, Any], passed_validation: bool) -> Path:
        """
        Speichert das Beleg-PDF nach dem Schema: YYYY-MM-DD_Lieferant_Bruttobetrag.pdf
        Im Fehlerfall in `00_Manuelle_Prüfung_Nötig`, sonst in `YYYY/MM/`.
        """
        datum_str = doc_data.get("datum", datetime.now().strftime("%Y-%m-%d"))
        try:
            dt = datetime.strptime(datum_str, "%Y-%m-%d")
            year_str = str(dt.year)
            month_str = f"{dt.month:02d}"
        except Exception:
            year_str = datetime.now().strftime("%Y")
            month_str = datetime.now().strftime("%m")

        lieferant = doc_data.get("lieferant", "Unbekannt").replace(" ", "_").replace("/", "_")
        brutto = doc_data.get("brutto", 0.0)
        filename = f"{datum_str}_{lieferant}_{brutto:.2f}EUR.pdf"

        if passed_validation:
            target_dir = self.base_dir / year_str / month_str
        else:
            target_dir = self.manual_review_dir

        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename

        with open(target_path, "wb") as f:
            f.write(pdf_bytes if pdf_bytes else b"%PDF-1.4 Mock Content")

        logger.info(f"[MockDrive] Datei gespeichert unter: {target_path}")
        return target_path


class MockTelegramBot:
    def __init__(self):
        pass

    def send_approval_request(self, doc_data: Dict[str, Any]) -> str:
        """
        Formatiert eine Telegram-Nachricht im Schreibstil von Vitalik mit Inline-Buttons.
        """
        lieferant = doc_data.get("lieferant")
        brutto = doc_data.get("brutto")
        skr = doc_data.get("skr03_konto", "3400")
        reason = doc_data.get("validation_reason", "")

        msg = f"""[VG Delikatessen Telegram Bot Notification]

Neuer Beleg erfasst:
- Lieferant: {lieferant}
- Datum: {doc_data.get('datum')}
- Brutto: {brutto:.2f} EUR (Netto: {doc_data.get('netto'):.2f} EUR, USt: {doc_data.get('steuer'):.2f} EUR)
- Soll-Konto (SKR03): {skr}
- Status: {doc_data.get('validation_status')} ({reason})

Aktion waehlen:
[ 1 ] Bestaetigen & in sevDesk buchen
[ 2 ] Zur manuellen Pruefung verschieben
"""
        return msg


class MockSevDeskClient:
    def __init__(self, file_path: Path = MOCK_SEVDESK_FILE):
        self.file_path = file_path
        self.buchungen = self._load_buchungen()

    def _load_buchungen(self) -> list:
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save_buchungen(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.buchungen, f, ensure_ascii=False, indent=2)

    def post_voucher(self, doc_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Bucht ein Dokument in der lokalen sevDesk-Simulation.
        """
        buchung_id = f"SEV-MOCK-{len(self.buchungen) + 1:04d}"
        entry = {
            "id": buchung_id,
            "timestamp": datetime.now().isoformat(),
            "lieferant": doc_data.get("lieferant"),
            "datum": doc_data.get("datum"),
            "brutto": doc_data.get("brutto"),
            "netto": doc_data.get("netto"),
            "steuer": doc_data.get("steuer"),
            "skr03_konto": doc_data.get("skr03_konto"),
            "status": "offen"
        }
        self.buchungen.append(entry)
        self._save_buchungen()
        logger.info(f"[MockSevDesk] Beleg gebucht unter ID {buchung_id}")
        return entry


# Globale Mock-Instanzen
mock_drive = MockGoogleDrive()
mock_telegram = MockTelegramBot()
mock_sevdesk = MockSevDeskClient()
