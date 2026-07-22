# E-Mail Intelligence & KI-Antwort-Entwurfs-Engine

Stand: 22. Juli 2026

Das System unterstützt das automatische Einlesen, Klassifizieren und Generieren von E-Mail-Antwortentwürfen für kaufmännische Vorgänge.

## 1. Dual E-Mail Fetcher (`email_fetcher.py`)
- **IMAP (SSL/TLS)**: Konfigurierbar für beliebige Mailserver (Strato, IONOS, Web.de, GMX, eigener Server).
- **Gmail API (OAuth2)**: Nativer Google Workspace Zugriff.
- Extrahiert E-Mail-Header, Nachrichtentext und entpackt PDF/DOCX/XLSX-Anhänge für die Ingestion-Pipeline.

## 2. E-Mail KI-Entscheidungs-Engine (`email_decision_engine.py`)
- Ordnet Absender dem deduplizierten `ContactMemory` zu.
- Klassifiziert die kaufmännische Absicht:
  - `RECHNUNG_INVOICE`: Rechnungen & Gutschriften.
  - `PREIS_ERHOEHUNG`: Benachrichtigungen über Preisanpassungen.
  - `LIEFERSCHEIN_DISCREPANCY`: Rückfragen zu Lieferungen/Fehlmengen.
  - `MAHNUNG_ZAHLUNGSERINNERUNG`: Zahlungserinnerungen.

## 3. KI-Antwort-Entwurfs-Generator (`email_draft_generator.py`)
- Erzeugt einen professionellen Antwort-Entwurf in Vitalis Tonalität.
- Speichert Entwürfe in der SQLite-Tabelle `email_drafts` mit Status `PENDING_APPROVAL`.
- **Sicherheit**: Es erfolgt kein automatischer Versand; Entwürfe werden im Dashboard (`http://localhost:8000`) zur Prüfung & Freigabe angezeigt.
