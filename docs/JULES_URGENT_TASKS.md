# Drei dringende, parallelisierbare Jules-Aufträge

Die Aufträge besitzen absichtlich getrennte Dateibereiche. Keine Sitzung darf
Produktions-PDFs, `data/rag_index.db`, `data/wiki/` oder private sevDesk-Daten
committen. Alle Tests müssen mit temporären Fixtures laufen.

## Auftrag 1 – Evidenzbasierte Bestandsabstimmung

**Branch:** `fix/evidence-based-contact-reconciliation`

Baue ein read-only-first Werkzeug
`src/core/reconcile_document_entities.py`, das historische Belege gegen
Kontaktgedächtnis, sevDesk-Kontakte und vorhandene Dateievidenz prüft.

Anforderungen:

- CLI mit `--db`, `--report`, `--dry-run` (Standard) und explizitem `--apply`;
- starke Identifikatoren USt-ID, IBAN, E-Mail und sevDesk-ID haben Vorrang;
- Dateiname oder Lieferantenname allein darf nie automatisch überschreiben;
- Widersprüche zwischen gespeichertem Lieferanten, OCR, PDF-Dateiname und Kontakt
  als `REVIEW_CONFLICT` ausgeben;
- sichere Treffer setzen idempotent `contact_entity_id`;
- keine Änderung an Dokumenten mit mehreren starken Kandidaten;
- Vorher-/Nachher-Zahlen, Konfliktliste und Audit-JSON schreiben;
- SQLite-Transaktion, automatisches Backup und Rollback bei Fehlern;
- Tests ausschließlich in `tests/test_entity_reconciliation.py`;
- nicht verändern: `src/wiki/wiki_engine.py`, `src/core/rag_engine.py`, Dashboard.

Akzeptanz: Wiederholung erzeugt keine Änderungen; fünf bekannte widersprüchliche
Frischeparadies-Fälle werden als Review erkannt und nicht blind korrigiert.

## Auftrag 2 – Rekursiver Wiki-Linter und Obsidian-Härtung

**Branch:** `fix/recursive-wiki-integrity`

Überarbeite ausschließlich Wiki-Qualitätswerkzeuge und lokale Vault-Konfiguration.

Anforderungen:

- `lint_wiki()` rekursiv über alle aktiven Markdown-Seiten;
- `archive/` konsequent aus Index, Graph, Suche und Lint ausschließen;
- kaputte Wiki- und Markdown-Links, Waisen, doppelte `entity_id`, doppelte Slugs,
  ungültiges Frontmatter und fehlende Quellen zählen;
- fehlende Artikelartseiten deterministisch aus dem Bestand erzeugen, keine
  einzelnen Artikelnodes;
- Frontmatter lesen, sodass Lieferanten als `lieferant` statt `Allgemein` im
  Index erscheinen;
- maschinenlesbaren JSON- und Markdown-Bericht erzeugen;
- sichere `.obsidian`-Voreinstellungen dokumentieren oder bereitstellen;
- Tests in `tests/test_wiki_integrity.py` mit temporärem Wiki;
- nicht verändern: Kontaktabgleich, RAG-Ranking, Produktions-Wiki-Daten.

Akzeptanz: Fixture mit Unterordnern, Archiv und kaputten Links liefert exakte
Zahlen; ein zweiter Reparaturlauf verändert keine Dateien mehr.

## Auftrag 3 – Reproduzierbarer RAG-Retrieval-Benchmark

**Branch:** `test/rag-retrieval-quality`

Erstelle `src/core/benchmark_rag_retrieval.py` und
`tests/test_rag_retrieval_benchmark.py` für die Suchqualität ohne echte LLMs.

Anforderungen:

- Ground-Truth-Format JSONL oder CSV mit Query, erwarteter Entität,
  erwarteten Belegen und erlaubten Kategorien;
- Metriken Hit@1, Hit@3, Hit@5, MRR, Duplicate-Rate und falsche-Entität-Rate;
- getrennte Auswertung für Entitätssuche, Rechnungsnummer, Zeitraum,
  Artikelart, Betrag und Kontierung;
- prüfen, dass eine exakte Lieferantensuche zuerst die Hubseite und anschließend
  unterschiedliche Belege liefert;
- strukturierte FTS- und OCR-Fallback-Treffer separat messen;
- `structural`/`fixture` vollständig offline, optionaler `live`-Modus;
- CSV-, JSON- und Markdown-Ausgabe unter frei wählbarem Output-Verzeichnis;
- mindestens 30 synthetische Queries und schwer absichtlich verwechselbare Namen;
- keine Änderung an `src/core/rag_engine.py`, Wiki-Engine oder Produktionsdaten.

Akzeptanz: reproduzierbarer Offline-Lauf, keine Netzwerk-/LM-Abhängigkeit und ein
Exitcode ungleich null, wenn konfigurierbare Mindestwerte unterschritten werden.
