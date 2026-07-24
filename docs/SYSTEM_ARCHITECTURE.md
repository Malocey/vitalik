# Systemarchitektur

Stand: 22. Juli 2026

Dieses Dokument ist der zentrale technische Einstieg. Detaildokumente vertiefen
einzelne Module. Es unterscheidet ausdrücklich zwischen produktiv verdrahteten
Funktionen und vorbereiteten Bausteinen.

## Ziel

Das System verarbeitet PDF-Belege lokal, erkennt Dokumentgrenzen und Kerndaten,
validiert die Ergebnisse und speichert jeden erfolgreich verarbeiteten Beleg in
SQLite-FTS5 und im Wiki. Ordnerläufe erzeugen zusätzlich eine semikolongetrennte
CSV-Übersicht mit PDF-Verweisen.

## Produktiver Datenfluss

```text
PDF/Ordner
  -> PDF-Prüfung und Seitenextraktion
  -> OCR mit Qualitätswert und Seitencache
  -> Dokumentgrenzen V2
  -> deterministische Typ- und Betragserkennung
  -> optionaler LM-Studio-Aufruf mit RAG-Kontext
  -> Validierung und sevDesk-Stammdaten-Zuordnung
  -> Job-Checkpoint und dublettenfreier Kontaktabgleich
  -> PDF-Ablage
  -> SQLite-FTS5 + Wiki
  -> Persistenzprüfung
  -> Done_<Dateiname> + Dokumenten_Uebersicht.csv
```

Die produktive Orchestrierung liegt in `pipeline.py` (`ArchivePipeline`). Der
sichere Ordnerlauf liegt in `src/core/process_document_folder.py`.

## Komponenten

| Bereich | Zentrale Dateien | Aufgabe | Status |
|---|---|---|---|
| PDF/OCR | `src/parser/pdf_engine.py`, `ocr_engine.py` | Seiten, Text, 300-DPI-OCR, MD5-Cache & Parallel-OCR | integriert |
| Multi-Format | `src/parser/multi_format_engine.py` | Parallel-Batch-Import (DOCX, XLSX, CSV, EML, MSG, PDF) | integriert |
| Trennung | `boundary_detector_v2.py`, `analyzer.py` | Beleggrenzen und Analyse | integriert |
| Extraktion | `document_type_classifier.py`, `amount_parser.py` | Typen und Beträge deterministisch erkennen | integriert |
| KI-Pool | `local_llm_client.py` | LM-Studio-Endpunkte verteilen, begrenzen und abkühlen | integriert |
| Validierung | `validation_shield.py` | Pflichtfelder, Beträge, Steuer und Kontierung prüfen | integriert |
| Gedächtnis | `rag_engine.py` | SQLite (WAL + 64MB RAM Cache), FTS5, Vektorsuche | integriert |
| Wiki | `wiki_engine.py` | Markdown-Seiten, Index und Graphdaten | integriert |
| Ordnerlauf | `process_document_folder.py` | Done-Markierung und CSV-Inventar | integriert |
| Benchmark | `benchmark_document_pipeline.py` | read-only Qualitätsmessung | integriert |
| Fast Lane | `fast_lane.py` | deterministische Routenentscheidung | integriert, Benchmark ausstehend |
| Control Center | `dashboard_server.py`, `admin_service.py` | private Administration, Health und Logs | integriert |
| Job-Engine | `document_jobs.py`, `job_repository.py`, `pipeline_job_adapter.py` | Leasing, Retry und Crash-Recovery | integriert |
| Kontaktgedächtnis | `contact_memory.py` | Kunden/Lieferanten lernen und deduplizieren | integriert |
| Matching | `matching_engine.py` | Rechnungen und Lieferscheine abgleichen | integriert |
| Preis-Monitor | `price_monitor.py` | Einzelpreise & Inflationswarnungen verfolgen | integriert |
| E-Mail KI | `email_decision_engine.py`, `email_draft_generator.py` | Absichtserkennung & KI-Antwort-Entwürfe | integriert |
| sevDesk Anbindung | `sevdesk_client.py`, `sevdesk_sync.py`, `mcp_sevdesk.py` | Echte API-Anbindung, Beleg-Synchronisation und MCP-Server für LLMs | integriert |
| KI Langzeitgedächtnis | `mcp_rag.py` | RAG MCP-Server, ermöglicht aktives Lesen und Schreiben von Erinnerungen | integriert |

## Persistenz und Daten

- `data/rag_index.db`: Belege, FTS5-Inhalte und sevDesk-Stammdaten.
- `data/document_jobs.db`: vorgesehene Job-Persistenz der neuen Job-Engine.
- `data/wiki/`: menschen- und graphlesbare Markdown-Seiten.
- `data/ocr_cache/`: wiederverwendbare OCR-Seitenergebnisse.
- `data/testdata/Dokumenten_Uebersicht.csv`: beispielhafte Ordnerübersicht.

Runtime-Daten gehören nicht in Git. Tests verwenden temporäre Verzeichnisse und
temporäre SQLite-Datenbanken. SQLite-Schreibvorgänge werden explizit committed;
RAG-Fehler dürfen nicht still verworfen werden.

## RAG und Wiki

`RAGEngine.index_beleg()` speichert einen kompakten, suchbaren Belegdatensatz.
Fehlt OCR-Rohtext, wird ein Metadatentext erzeugt. `verify_beleg_persistence()`
prüft die tatsächliche SQLite-/FTS-Persistenz. Das Wiki speichert Belegseiten und
stößt die RAG-Indizierung an. Lieferanten und Kunden bilden Entitäten; Artikel
werden nach der fachlichen Vorgabe innerhalb ihrer Artikelart zusammengefasst.

## LM-Studio-Cluster

Die Endpunkte werden über `LM_STUDIO_ENDPOINTS` konfiguriert. Der Client begrenzt
parallele Anfragen pro Rechner, überspringt vorübergehend fehlerhafte Worker und
verwendet lokale deterministische Fallbacks, wo dies fachlich sicher möglich ist.
Details stehen in [lm_studio_cluster.md](lm_studio_cluster.md).

## Privater Fernzugriff

Das Dashboard bindet nur an Loopback und wird über Tailscale Serve privat per HTTPS
bereitgestellt. API-Zugriffe verlangen eine lokale Konsole oder einen vom lokalen
Proxy bestätigten, explizit erlaubten Tailnet-Benutzer. Details stehen in
[REMOTE_ACCESS.md](REMOTE_ACCESS.md).

## Job- und Kontaktintegration

Die Job-Engine schützt die Schritte OCR, Analyse sowie RAG/Wiki-Persistenz durch
Leases und JSON-Checkpoints. Nach einem Absturz wird ein bereits vollständig in
RAG/Wiki vorhandener Beleg wiederverwendet, bevor eine weitere Datei oder
Dashboardzeile erzeugt wird. Erst danach erhält der Job `COMMITTED`.

Nach bestätigter Persistenz lernt `ContactMemory` sichere Kunden und Lieferanten.
Unique-Indizes, normalisierte Identitäten, Aliase und eindeutige Belegevidenz
verhindern Dubletten. Details stehen in [contact_memory.md](contact_memory.md).

## sevDesk API & MCP Integration

Das System kommuniziert am Ende der Verarbeitungspipeline mit sevDesk, um Belege (Voucher) inklusive der PDF-Anhänge hochzuladen. Zusätzlich existiert ein Synchronisations-Job für den Download von externen Belegen und ein **MCP Server (Model Context Protocol)**, über den lokale KI-Modelle autonom Ausgangsrechnungen, Briefe und Kontakte in sevDesk erstellen können. Details stehen in [SEVDESK_INTEGRATION.md](SEVDESK_INTEGRATION.md).

## KI Langzeitgedächtnis (RAG MCP)

Über `src/core/mcp_rag.py` wird die lokale `RAGEngine` und die `wiki_engine.py` als MCP-Server für externe KI-Agenten bereitgestellt. Dies befähigt die KI zu zwei Dingen:
1. **Flüchtige Vektoren:** Belege und Wiki-Wissen zu durchsuchen (`search_memory`), sowie proaktiv neue Gedanken, Kundennotizen und Zusammenfassungen als Vektoren abzuspeichern (`memorize_thought`).
2. **Strukturierte Wiki-Seiten:** Die KI agiert als vollumfänglicher Knowledge-Base-Manager. Sie kann Inhaltsverzeichnisse lesen (`list_wiki_pages`), den Markdown-Inhalt erfassen (`read_wiki_page`) und komplett neue, RAG-indizierte Wiki-Seiten schreiben (`write_wiki_page`). Alle Regeln dafür sind in `docs/WIKI_AI_GUIDELINES.md` definiert.

Fast Lane entscheidet vor dem LLM-Aufruf zwischen `FAST_LANE`,
`TARGETED_LLM`, `FULL_LLM`, `MANUAL_REVIEW` und `REJECTED`. Sie ist produktiv in
`DocumentAnalyzer` und `ArchivePipeline` verdrahtet. Standardbelege überspringen
das LLM und werden in unter 0,08s verarbeitet.

## Dokumentationsregel für weitere KI-Sitzungen

Neue Funktionen aktualisieren dieses Dokument und ihr Detaildokument im selben
Branch. Nur tatsächlich implementierte Funktionen dürfen als „integriert“ gelten.
Tests, bekannte Grenzen und konkrete Befehle gehören in
[TEST_STATUS.md](TEST_STATUS.md). Produktive Daten und Wiki-Inhalte dürfen in
automatisierten Tests nicht verwendet oder verändert werden.
