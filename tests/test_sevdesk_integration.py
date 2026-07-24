import pytest
import json
from src.core.mcp_sevdesk import get_sevdesk_status, create_customer_invoice
from src.core.sevdesk_client import SevDeskClient
from src.core.config import USE_MOCK_SEVDESK

# Wir testen hier in erster Linie die Formatierung der JSON-Payloads und das MCP-Interface.

def test_mcp_status_tool():
    """Testet das einfache Status-Tool des MCP Servers."""
    status = get_sevdesk_status()
    assert isinstance(status, str)
    if USE_MOCK_SEVDESK:
        assert "MOCK-Modus" in status
    else:
        assert "LIVE-Modus" in status

def test_mcp_create_invoice_mock():
    """Testet die Rechnungserstellung über das MCP Tool im Mock-Modus."""
    # Temporär den Mock erzwingen, falls in der .env False steht
    import src.core.mcp_sevdesk as mcp_mod
    original_mock = mcp_mod.USE_MOCK_SEVDESK
    mcp_mod.USE_MOCK_SEVDESK = True

    try:
        res_str = create_customer_invoice("123", "Catering", "Buffet", 500.0, 1)
        res = json.loads(res_str)
        assert res["status"] == "success"
        assert "Mock" in res["message"]
        assert res["invoice_data"]["header"] == "Catering"
    finally:
        mcp_mod.USE_MOCK_SEVDESK = original_mock

class DummyResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code
        self.text = json.dumps(json_data)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP Error")

    def json(self):
        return self._json_data

def test_sevdesk_client_invoice_payload(monkeypatch):
    """
    Stellt sicher, dass das Payload-Format für Invoices korrekt
    zusammengesetzt wird (ohne echte Netzwerk-Aufrufe).
    """
    client = SevDeskClient(token="dummy")

    # Wir fangen den Request ab, um den generierten Payload zu prüfen
    captured_payload = {}
    def mock_request(method, url, headers=None, json=None, **kwargs):
        nonlocal captured_payload
        captured_payload = json
        return DummyResponse({"objects": {"id": "new_invoice_99"}})

    # Patchen von requests.request
    import requests
    monkeypatch.setattr(requests, "request", mock_request)

    # Testaufruf
    result = client.create_invoice({
        "contact_id": "88",
        "header": "Festmahl",
        "positions": [
            {"name": "Steak", "price": 45.0, "quantity": 2, "taxRate": 7}
        ]
    })

    assert result == {"id": "new_invoice_99"}
    assert "invoice" in captured_payload
    assert "invoicePosSave" in captured_payload

    assert captured_payload["invoice"]["header"] == "Festmahl"
    assert captured_payload["invoice"]["contact"]["id"] == "88"

    pos = captured_payload["invoicePosSave"][0]
    assert pos["name"] == "Steak"
    assert pos["price"] == 45.0
    assert pos["quantity"] == 2
    assert pos["taxRate"] == 7
