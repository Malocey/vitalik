import argparse
import json
import logging
from typing import Dict, Any

from src.core.local_llm_client import default_llm_client
from src.core.persona_style import persona_engine
from src.core.sevdesk_client import sevdesk_client
from src.core.contact_memory import contact_memory
from src.core.config import USE_MOCK_SEVDESK

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("InvoiceGenerator")

def generate_invoice_data(prompt: str) -> Dict[str, Any]:
    """
    Nutzt das LLM, um aus dem unstrukturierten Text (prompt) eine strukturierte
    Rechnung zu generieren (JSON-Format).
    """
    system_prompt = (
        "Du bist ein Assistent, der aus Notizen eine strukturierte Rechnung im JSON-Format erstellt. "
        "Die JSON-Struktur MUSS so aussehen:\n"
        "{\n"
        '  "customer_name": "Name des Kunden aus dem Text",\n'
        '  "header": "Ein passender Rechnungstitel",\n'
        '  "positions": [\n'
        '    {"name": "Positionsbeschreibung", "quantity": 1, "price": 100.00, "taxRate": 19}\n'
        "  ]\n"
        "}\n"
        "Gib NUR das reine JSON zurück. Keine Erklärungen, keine Markdown-Blöcke (```json)."
    )

    # Optional: Den Schreibstil von Vitali ins System laden (wenn es ein Anschreiben wäre)
    # Hier fokussieren wir uns nur auf Datenextraktion, aber bei "Letters" wäre persona_engine wichtig.

    logger.info(f"Sende Anfrage an lokales LLM für: '{prompt}'")
    response_text = default_llm_client.generate_completion(prompt, system_prompt=system_prompt)

    # Bereinigen, falls das LLM trotz Anweisung Markdown nutzt
    response_text = response_text.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(response_text)
        logger.info(f"Vom LLM generierte Rechnungsdaten: {json.dumps(data, indent=2)}")
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Konnte LLM-Antwort nicht als JSON parsen. Antwort war:\n{response_text}")
        raise ValueError("Ungültiges JSON vom LLM zurückgegeben.") from e

def resolve_contact(customer_name: str) -> str:
    """
    Versucht, einen Kontakt lokal oder in sevDesk zu finden.
    Legt im Zweifel einen neuen Dummy-Kontakt in sevDesk an, wenn keiner gefunden wird.
    Gibt die sevDesk contact_id zurück.
    """
    # 1. Wir checken das lokale Kontaktgedächtnis (nur für Logik/Beispiel, liefert aktuell DB IDs)
    # In einer perfekten Welt würde contact_memory auch die sevDesk-IDs speichern.

    if USE_MOCK_SEVDESK:
        return "12345" # Mock ID

    # 2. In sevDesk nach dem Namen suchen
    logger.info(f"Suche nach Kunde '{customer_name}' in sevDesk...")
    contacts = sevdesk_client.get_contacts(depth=0)

    for c in contacts:
        # Sehr einfaches Matching
        if c.get("name") and customer_name.lower() in c.get("name", "").lower():
            contact_id = c.get("id")
            logger.info(f"Kunde gefunden in sevDesk: ID {contact_id}")
            return contact_id

    # 3. Falls nicht gefunden, legen wir ihn neu an
    logger.info(f"Kunde '{customer_name}' nicht gefunden. Lege neu an...")
    new_contact = sevdesk_client.create_contact({
        "name": customer_name,
        "category_id": 4 # 4 = Kunde (in der Regel)
    })
    new_id = new_contact.get("id")
    if new_id:
        return new_id

    raise RuntimeError("Konnte keinen Kontakt in sevDesk anlegen oder finden.")

def main():
    parser = argparse.ArgumentParser(description="KI-gestützter Rechnungsgenerator für sevDesk")
    parser.add_argument("text", type=str, help="Notiz oder Stichpunkte für die Rechnung, z.B. 'Rechnung an Müller für Catering 500 Euro'")
    args = parser.parse_args()

    try:
        # Schritt 1: LLM wandelt Notiz in strukturierte Daten um
        invoice_json = generate_invoice_data(args.text)

        # Schritt 2: Kunden-ID auflösen/anlegen
        contact_id = resolve_contact(invoice_json["customer_name"])
        invoice_json["contact_id"] = contact_id

        # Schritt 3: In sevDesk anlegen
        if USE_MOCK_SEVDESK:
            logger.info(f"[Mock] Würde Rechnung anlegen: {invoice_json}")
        else:
            logger.info("Übertrage Rechnung an sevDesk API...")
            result = sevdesk_client.create_invoice(invoice_json)

            # Ausgabe für Vitali (Konsolen-Erfolg)
            invoice_obj = result.get("invoice", {})
            logger.info("=========================================")
            logger.info(f"Erfolg! Rechnung (Entwurf) in sevDesk erstellt.")
            logger.info(f"Rechnungsnummer: {invoice_obj.get('invoiceNumber', 'Entwurf')}")
            logger.info(f"ID: {invoice_obj.get('id')}")
            logger.info("=========================================")

    except Exception as e:
        logger.error(f"Fehler bei der Rechnungsgenerierung: {e}")

if __name__ == "__main__":
    main()
