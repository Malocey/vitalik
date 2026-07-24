import logging
from pathlib import Path
from src.core.config import USE_MOCK_SEVDESK
from src.core.sevdesk_client import sevdesk_client
from src.core.rag_engine import rag_engine
import shutil
import uuid

logger = logging.getLogger("SevDeskSync")

class SevDeskSyncJob:
    def __init__(self, target_dir: Path = Path("data/downloads/sevdesk")):
        self.target_dir = target_dir
        self.target_dir.mkdir(parents=True, exist_ok=True)

    def _beleg_exists_locally(self, voucher: dict) -> bool:
        """
        Prüft rudimentär, ob ein sevDesk-Beleg bereits lokal (z.B. in der SQLite/RAG) vorliegt.
        Matching anhand Belegnummer, Datum oder Betrag könnte hier genauer implementiert werden.
        """
        # Aktuell prüfen wir z.B. nur, ob wir einen sevdesk_id Index hätten (falls implementiert)
        # Für den RAG-Index können wir z.B. nach der Voucher-Nummer (Rechnungsnummer) oder dem Betrag suchen

        voucher_nr = voucher.get("voucherNumber")
        amount = voucher.get("amountGross")
        date = voucher.get("voucherDate", "")[:10]

        if voucher_nr:
            # Einfaches Query im RAG
            results = rag_engine.search(voucher_nr, top_k=1)
            if results and results[0]["score"] > 0.8:
                return True

        # Alternativ auch über Lieferant + Betrag etc.
        return False

    def sync_vouchers(self):
        """
        Lädt alle aktuellen Belege aus sevDesk und importiert fehlende in die lokale KI.
        """
        if USE_MOCK_SEVDESK:
            logger.info("[SevDeskSync] USE_MOCK_SEVDESK ist aktiv. Synchronisation übersprungen.")
            return

        logger.info("[SevDeskSync] Starte Synchronisation von sevDesk Belegen...")

        try:
            vouchers = sevdesk_client.get_vouchers(status="50")
            logger.info(f"[SevDeskSync] {len(vouchers)} offene Belege in sevDesk gefunden.")

            downloaded = 0
            for v in vouchers:
                voucher_id = str(v.get("id"))

                if self._beleg_exists_locally(v):
                    logger.debug(f"[SevDeskSync] Beleg {voucher_id} existiert bereits lokal.")
                    continue

                # Herunterladen
                logger.info(f"[SevDeskSync] Lade neuen Beleg herunter: {voucher_id}")
                downloaded_file = sevdesk_client.download_voucher_file(voucher_id, self.target_dir)

                if downloaded_file:
                    downloaded += 1
                    # Hier könnte man die Datei z.B. in einen Ingestion-Ordner verschieben
                    # damit die Pipeline sie später abgreift, oder wir stoßen es direkt an.
                    # Beispiel: verschieben in data/testdata/ (oder wo auch immer der Inbox-Ordner ist)

                    inbox_dir = Path("data/inbox")
                    inbox_dir.mkdir(parents=True, exist_ok=True)
                    target_inbox = inbox_dir / downloaded_file.name
                    shutil.move(str(downloaded_file), str(target_inbox))
                    logger.info(f"[SevDeskSync] Beleg {voucher_id} in {target_inbox} verschoben.")

            logger.info(f"[SevDeskSync] Synchronisation abgeschlossen. {downloaded} neue Belege importiert.")

        except Exception as e:
            logger.error(f"[SevDeskSync] Fehler bei der Synchronisation: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    job = SevDeskSyncJob()
    job.sync_vouchers()
