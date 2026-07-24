import json
from typing import Dict, Any, List
from fastmcp import FastMCP
from src.core.sevdesk_client import sevdesk_client
from src.core.config import USE_MOCK_SEVDESK

# Initialize FastMCP server
mcp = FastMCP("sevDesk")

@mcp.tool()
def get_sevdesk_status() -> str:
    """Zeigt an, ob die sevDesk API im Mock-Modus oder live läuft."""
    if USE_MOCK_SEVDESK:
        return "sevDesk läuft im MOCK-Modus. Es werden keine echten Daten gesendet oder abgerufen."
    return "sevDesk läuft im LIVE-Modus. Daten werden mit dem echten Account synchronisiert."

@mcp.tool()
def get_open_vouchers() -> str:
    """Ruft eine Liste von offenen Belegen (Vouchers) aus sevDesk ab."""
    if USE_MOCK_SEVDESK:
        return json.dumps([{"id": "mock-1", "description": "Mock Beleg"}])
    try:
        vouchers = sevdesk_client.get_vouchers("50")
        return json.dumps(vouchers, indent=2)
    except Exception as e:
        return f"Fehler beim Abrufen der Belege: {e}"

@mcp.tool()
def search_contacts(name_query: str) -> str:
    """Sucht nach Kontakten in sevDesk anhand eines Namens."""
    if USE_MOCK_SEVDESK:
        return json.dumps([{"id": "mock-contact-1", "name": f"Mock Kontakt für {name_query}"}])
    try:
        contacts = sevdesk_client.get_contacts()
        results = [c for c in contacts if name_query.lower() in str(c.get("name", "")).lower()]
        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Fehler bei der Kontaktsuche: {e}"

@mcp.tool()
def create_customer_invoice(customer_id: str, title: str, item_name: str, price: float, quantity: int = 1) -> str:
    """
    Erstellt einen Entwurf für eine Ausgangsrechnung in sevDesk.
    customer_id: Die sevDesk Kontakt-ID.
    title: Titel der Rechnung (z.B. "Catering Wochenende")
    item_name: Name der Position (z.B. "Buffet")
    price: Einzelpreis der Position in Euro
    quantity: Menge (Standard: 1)
    """
    if USE_MOCK_SEVDESK:
        return json.dumps({
            "status": "success",
            "message": "Rechnung (Mock) wurde erfolgreich erstellt",
            "invoice_data": {"header": title, "contact_id": customer_id}
        })

    try:
        invoice_data = {
            "contact_id": customer_id,
            "header": title,
            "positions": [
                {"name": item_name, "price": price, "quantity": quantity, "taxRate": 19}
            ]
        }
        result = sevdesk_client.create_invoice(invoice_data)
        return json.dumps({
            "status": "success",
            "message": "Rechnung (Entwurf) wurde erfolgreich in sevDesk erstellt.",
            "data": result
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@mcp.tool()
def write_business_letter(contact_id: str, subject: str, text: str) -> str:
    """
    Erstellt einen Geschäftsbrief als Entwurf in sevDesk.
    """
    if USE_MOCK_SEVDESK:
        return json.dumps({"status": "success", "message": f"Brief (Mock) an {contact_id} erstellt."})
    try:
        letter_data = {
            "contact_id": contact_id,
            "subject": subject,
            "text": text
        }
        result = sevdesk_client.create_letter(letter_data)
        return json.dumps({"status": "success", "data": result})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

if __name__ == "__main__":
    # Startet den Server (Standardmäßig stdio, ideal für lokale LLM Runner wie Claude Desktop, LM Studio etc.)
    mcp.run()
