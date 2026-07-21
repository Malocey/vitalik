# Teststatus und Sicherheitsanalyse

Stand: 22. Juli 2026, Integrationsbranch `integration/fast-lane-resumable-jobs`

## Reproduzierbarer Lauf

```bash
python3 -m pytest -q
```

Ergebnis auf macOS mit Python 3.9.6:

```text
100 passed, 4 warnings in 3.25s
```

Die vier Warnungen stammen von `urllib3`/LibreSSL und Hinweisen externer
Google-Bibliotheken auf das Ende des Python-3.9-Supports. Es gab keine fachlichen
Testfehler. Mittelfristig sollte die Laufzeitumgebung mindestens Python 3.10,
vorzugsweise eine aktuell unterstützte Version, verwenden.

## Neue Module

```bash
python3 -m pytest -q tests/test_fast_lane.py tests/test_document_jobs.py
```

Ergebnis:

```text
33 passed in 2.33s
```

Davon prüfen 22 Fast-Lane-Tests Routing, Konflikte, fehlende Felder,
geschützte Dokumenttypen, Batchmetriken und Schätzwerte. Elf Job-Tests prüfen
Idempotenz, exklusive Leases, Ablauf, Retry, alte Worker, finale Zustände,
Fortschrittszahlen und parallele SQLite-Zugriffe.

## Befunde der Integrationsprüfung

Die ursprünglichen Jules-Branches bestanden ihre eigenen Tests (16/16 und 8/8),
ließen aber mehrere nicht getestete Randfälle zu. Vor der Integration wurden
deshalb folgende Fehler behoben und mit Regressionstests abgesichert:

- explizite Eingabefehler und textlose Seiten konnten die Fast Lane erreichen;
- Boundary-, Lieferanten- und Rechnungsnummernkonflikte blockierten nicht sicher;
- drei vollständig fehlende Betragsfelder wurden nur als ein Feld gezählt;
- geschützte Dokumenttypen wurden groß-/kleinschreibungsabhängig verglichen;
- abgelaufene Lease-Besitzer konnten verlängern und Statusänderungen committen;
- finale Jobs konnten direkt über die Repository-Schnittstelle erneut geleast werden;
- der sevDesk-Zuordnungstest verlangte lokale Produktionsdaten und war in einem
  frischen Checkout nicht reproduzierbar. Er erzeugt nun eigene Testdaten in einer
  temporären SQLite-Datenbank.

## Was die Tests noch nicht beweisen

- Fast Lane und Job-Engine sind noch nicht in `ArchivePipeline` verdrahtet.
- Es gibt noch keinen End-to-End-Crashtest zwischen RAG-, Wiki- und Job-Commit.
- Die Fast-Lane-Einsparungen sind Schätzungen, noch keine Messungen echter Gemma-Läufe.
- SQLite-Paralleltests laufen lokal in Threads; mehrere Prozesse und Netzwerk-
  Dateisysteme brauchen einen gesonderten Belastungstest.
- Die echte Belegerkennungsqualität muss mit repräsentativen, anonymisierten PDFs
  und Erwartungsdaten über den Benchmark gemessen werden.

## Nächste Abnahmekriterien

Vor produktiver Aktivierung der neuen Module müssen ein Pipeline-Adapter,
atomare/idempotente RAG-Wiki-Commits, Crash-Injection-Tests und ein gemessener
Fast-Lane-A/B-Benchmark hinzukommen. Bis dahin bleiben die Module vorbereitet,
aber nicht automatisch aktiv.
