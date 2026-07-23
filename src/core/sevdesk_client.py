import logging
import requests
from pathlib import Path
from typing import Dict, Any, List, Optional
from src.core.config import SEVDESK_API_TOKEN

logger = logging.getLogger("SevDeskClient")

class SevDeskClient:
    BASE_URL = "https://my.sevdesk.de/api/v1"

    def __init__(self, token: str = SEVDESK_API_TOKEN):
        self.token = token
        self.headers = {
            "Authorization": self.token,
            "Accept": "application/json"
        }

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        headers = kwargs.pop("headers", self.headers)

        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()

            if response.status_code == 204: # No content
                return {}

            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"[SevDesk] API Fehler bei {method} {url}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"[SevDesk] Response body: {e.response.text}")
            raise

    def get_vouchers(self, status: str = "50") -> List[Dict[str, Any]]:
        """
        Gibt eine Liste von Belegen zurück.
        status: z.B. 50 (offen), 1000 (bezahlt). "100" = drafts.
        Default: 50
        """
        data = self._request("GET", "Voucher", params={"status": status})
        return data.get("objects", [])

    def create_voucher(self, doc_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Erstellt einen Beleg (Voucher) in sevDesk.
        """
        import datetime

        datum_str = doc_data.get("datum", datetime.datetime.now().strftime("%Y-%m-%d"))
        try:
            dt = datetime.datetime.strptime(datum_str, "%Y-%m-%d")
            formatted_date = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        except ValueError:
            formatted_date = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")

        # Beispielhafter Payload. In einer echten Umgebung müssten Lieferant (Contact) und Konto (Category)
        # vorher als Entitäten in sevDesk aufgelöst werden.
        payload = {
            "voucher": {
                "voucherDate": formatted_date,
                "status": "50", # Entwurf/Offen
                "taxType": "default",
                "description": f"Import von VG Delikatessen: {doc_data.get('lieferant', 'Unbekannt')}",
                "amountNet": doc_data.get("netto", 0.0),
                "amountTax": doc_data.get("steuer", 0.0),
                "amountGross": doc_data.get("brutto", 0.0),
            }
        }

        # Hinweis: Um es als Beleg anzulegen, braucht man eine Position.
        # Das hier ist ein vereinfachtes Format zum Erstellen eines Factory-Objekts,
        # oft verlangt die API einen Factory-Endpoint, z.B. Voucher/Factory/saveVoucher

        response = self._request("POST", "Voucher/Factory/saveVoucher", json=payload)
        return response.get("objects", {})

    def upload_voucher_file(self, voucher_id: str, file_path: Path) -> Dict[str, Any]:
        """
        Lädt eine Datei (PDF, PNG, JPG) zu einem bestehenden Beleg hoch.
        """
        url = f"{self.BASE_URL}/Voucher/{voucher_id}/uploadFile"

        with open(file_path, "rb") as f:
            files = {
                "file": (file_path.name, f, "application/octet-stream") # oder mimetypes erraten
            }
            # The Content-Type is determined by requests automatically when passing files
            # But we must remove it from self.headers so it creates the multipart boundary
            upload_headers = self.headers.copy()
            upload_headers.pop("Content-Type", None)

            try:
                response = requests.post(url, headers=upload_headers, files=files)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f"[SevDesk] Fehler beim Dateiupload: {e}")
                raise

    def download_voucher_file(self, voucher_id: str, target_dir: Path) -> Optional[Path]:
        """
        Lädt das angehängte PDF/Bild eines Belegs herunter.
        """
        # Laut Doku holt man die angehängten Dokumente via Document-Endpoint oder direkt auf Voucher/id/getPdf
        # Beachte: Für Belege (Voucher) liefert getPdf evtl. nur das PDF des erzeugten Vouchers (z.B. Rechnung),
        # für hochgeladene Dateien müssen wir oft die referenzierten Document-Objekte holen.
        # Aber der Einfachheit halber probieren wir erst getPdf, da sevDesk oft einen PDF-Wrapper baut.

        endpoint = f"Voucher/{voucher_id}/getPdf"
        # Often getPdf expects "download" param or accepts GET

        url = f"{self.BASE_URL}/{endpoint}"
        try:
            response = requests.get(url, headers=self.headers, stream=True)
            response.raise_for_status()

            target_path = target_dir / f"sevdesk_{voucher_id}.pdf"
            with open(target_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return target_path
        except requests.exceptions.RequestException as e:
            logger.error(f"[SevDesk] Fehler beim Download des Belegs {voucher_id}: {e}")
            return None

# Globale Instanz, die bei Bedarf geladen wird
sevdesk_client = SevDeskClient()
