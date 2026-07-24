# sevDesk Integration & MCP-Server

Dieses Modul verbindet das "Digitale Nervensystem" von VG Delikatessen mit der Buchhaltungssoftware sevDesk. Die Integration ermöglicht den beidseitigen Abgleich von Belegen, das automatisierte Erstellen von Ausgangsrechnungen durch KI und bietet einen **Model Context Protocol (MCP)** Server, über den lokale LLMs selbstständig mit sevDesk interagieren können.

## 1. Konfiguration

Die Anbindung wird über die `.env`-Datei gesteuert.

```env
# sevDesk Integration
SEVDESK_API_TOKEN=dein_echter_sevdesk_api_token
USE_MOCK_SEVDESK=True
```

- `SEVDESK_API_TOKEN`: Der API-Schlüssel aus den sevDesk Benutzereinstellungen.
- `USE_MOCK_SEVDESK`: Ein Sicherheitsschalter. Steht er auf `True`, werden keine Netzwerk-Aufrufe getätigt. Alle Aktionen (wie das Buchen von Belegen am Ende der Pipeline) nutzen dann die lokale Mock-Datei `data/mock_storage/sevdesk_buchungen.json`. Für den produktiven Betrieb auf `False` setzen.

## 2. Architektur & Module

Um die absolute Offline-Pflicht der Dokumentenanalyse-Pipeline nicht zu verletzen, finden externe Aufrufe **immer erst nach dem Speichern** des Belegs statt.

### 2.1 API-Client (`src/core/sevdesk_client.py`)
Ein direkter, leichtgewichtiger HTTP-Client via `requests`, der auf das Generieren überladener OpenAPI-Wrapper verzichtet. Er stellt Endpunkte bereit für:
- Belege (Vouchers) inkl. Datei-Upload (`getPdf`, `uploadFile`, `saveVoucher`)
- Rechnungen (Invoices)
- Geschäftsbriefe (Letters)
- Kontakte (Contacts) und Transaktionen

### 2.2 Rechnungsgenerator (`src/core/generate_invoice.py`)
Ein CLI-Tool, das Notizen über das lokale LLM in saubere JSON-Strukturen überführt.
**Aufruf:**
```bash
python3 src/core/generate_invoice.py "Rechnung an Müller für Catering Wochenende 500 Euro"
```
Das Skript formatiert die Daten, ordnet den Kontakt in sevDesk zu (oder legt ihn an) und generiert den Rechnungsentwurf (Status 100).

### 2.3 Synchronisations-Job (`src/core/sevdesk_sync.py`)
Sucht nach offenen Belegen, die extern (z.B. per App) in sevDesk hochgeladen wurden. Mittels lokaler RAG-Suche (Rechnungsnummer etc.) wird ein Dublettenabgleich durchgeführt. Fehlt der Beleg im KI-Gedächtnis, wird das PDF heruntergeladen und zur Verarbeitung in die lokale Inbox übergeben.

## 3. MCP-Server (Model Context Protocol)

Das absolute Highlight ist der MCP-Server (`src/core/mcp_sevdesk.py`). Er ermöglicht es KI-Anwendungen (wie Claude Desktop, Cursor oder LM Studio), die sevDesk-Funktionen dynamisch als "Werkzeuge (Tools)" zu verwenden.

Die KI kann somit auf Sprachbefehl:
- "Zeige mir alle offenen Belege aus sevDesk." (`get_open_vouchers`)
- "Suche nach dem Kunden Müller." (`search_contacts`)
- "Schreibe eine Rechnung an Kunde ID 123 über 1000€ für Buffet." (`create_customer_invoice`)
- "Erstelle einen Geschäftsbrief für diesen Kunden." (`write_business_letter`)

### 3.1 Einrichtung in Claude Desktop
Um den lokalen sevDesk MCP-Server in **Claude Desktop** (oder kompatiblen Clients) einzubinden, füge folgende Konfiguration in die `claude_desktop_config.json` ein:

```json
{
  "mcpServers": {
    "sevdesk_local": {
      "command": "/Pfad/zu/deinem/python3",
      "args": [
        "/Pfad/zum/vitalik-Repo/src/core/mcp_sevdesk.py"
      ],
      "env": {
        "USE_MOCK_SEVDESK": "False",
        "SEVDESK_API_TOKEN": "dein_sevdesk_token"
      }
    }
  }
}
```

Nach einem Neustart der Claude-App wird das Hammer-Symbol (Tools) unten rechts angezeigt, und Claude kann vollkommen autonom Rechnungen für VG Delikatessen entwerfen.

## 4. Sicherheitsrichtlinien

- **Offline First:** Keine Analysefunktion darf `sevdesk_client` importieren.
- **Transaktional:** Das Hochladen der PDF (`upload_voucher_file`) darf nur erfolgen, wenn die zugehörige Beleg-ID (Voucher-ID) sicher vorhanden ist.
