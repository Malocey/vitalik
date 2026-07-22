# Wiki-Audit vom 22. Juli 2026

## Kurzfazit

Die Trennung zwischen Belegarchiv und verdichtetem Wiki funktioniert. Es gibt
keine aktiven Einzelbeleg-Nodes mehr. Vor dem Dokumententest müssen jedoch
Bestandszuordnungen, Linkintegrität und der Wiki-Linter gehärtet werden.

## Gemessener Bestand

- 104 aktive Markdown-Seiten ohne Archiv
- 8 Lieferanten-Hubseiten
- 80 sevDesk-Kontaktseiten
- 4 Artikel-/Kontaktartseiten
- eine gemeinsame Prüfseite mit 6 ungeklärten Belegen
- 69 produktive SQLite-Belege
- 69 strukturierte FTS-Einträge und 69 OCR-Fallback-Einträge

## Dringende Befunde

1. Fünf Belege sind Frischeparadies zugeordnet, obwohl der gespeicherte PDF-Name
   Jensmann oder Transgourmet nennt (`VG-0004`, `VG-0008`, `VG-0012`,
   `VG-0014`, `VG-0015`). Das ist ein starker Widerspruch, aber noch kein
   automatischer Beweis für den korrekten Lieferanten.
2. 53 von 69 produktiven Belegen besitzen keinen Status `PASSED`.
3. Alle 69 historischen Belege haben noch keine `contact_entity_id`. Die neuen
   Seiten sind deshalb momentan über normalisierte Namen statt starke IDs gebündelt.
4. Elf Wiki-Links zeigen auf vier fehlende Artikelarten:
   `Bankdokument`, `Betriebsbedarf`, `Fleischwaren`, `Sonstiges`.
5. Vier gespeicherte Beleglinks sind nicht als lokale Datei auflösbar; drei davon
   sind bekannte Dubletten-Platzhalter.
6. Der vorhandene `lint_wiki()` prüft nur das Wiki-Hauptverzeichnis und meldet
   deshalb fälschlich nur zehn Seiten statt des vollständigen rekursiven Bestands.
7. Die Hubseiten erscheinen im Index teilweise als `Allgemein`; Frontmatter und
   Kategorielesung müssen vereinheitlicht werden.

## Empfohlene Obsidian-Einstellungen

- Vault-Verzeichnis: `data/wiki`
- interne Links automatisch aktualisieren
- neue Links relativ zur aktuellen Datei erzeugen
- Anhänge künftig zentral unter `assets/` speichern
- Graph-Filter: `-path:"archive" -path:"review"`
- Properties/Frontmatter sichtbar lassen; `entity_id`, `entity_type`,
  `source_count`, `updated`, `article_categories` und `skr03_accounts` nicht
  manuell umbenennen
- das Archiv nur bei einer gezielten Quellenprüfung einblenden

Die Obsidian-Einstellung ist Komfort. Für die RAG-Funktion sind keine Plugins
notwendig. Dataview kann später ergänzend verwendet werden, darf aber keine
Voraussetzung für Persistenz oder Suche werden.

## Reihenfolge vor dem Dokumententest

1. Bestandszuordnungen evidenzbasiert prüfen und `contact_entity_id` nachpflegen.
2. Wiki-Linter, Kategorien, Index und Graph vollständig korrigieren.
3. Reproduzierbaren RAG-Retrieval-Benchmark erstellen.
4. Danach Pilotlauf mit 30 Dokumenten starten.

## Ergebnis nach Integration des rekursiven Linters

Der neue Linter wurde am 22. Juli 2026 read-only gegen `data/wiki` und
`data/rag_index.db` ausgeführt. Der Lauf prüfte 102 Fachseiten (Index und Log
werden absichtlich nicht mitgezählt) und ließ den Wiki-Bestand unverändert.

- Status: `ISSUES_FOUND`
- 15 Seiten ohne eingehenden Link
- 11 kaputte Wikilinks zu 4 fehlenden Artikelarten
- keine doppelten Slugs oder `entity_id`-Werte
- keine fehlenden Belegquellen in SQLite
- 90 ältere/importierte Seiten ohne das neue vollständige Frontmatter-Schema
- 3 ausdrücklich tolerierte Legacy-Seiten

Die 90 Frontmatter-Meldungen bedeuten nicht, dass die sevDesk-Daten verloren
sind. Sie zeigen den noch offenen Schema-Migrationsbedarf. Der automatische
`--repair`-Modus wurde deshalb bewusst nicht auf Produktivdaten angewendet.

Integrationsprüfung des gesamten Projekts: **173 Tests bestanden**. Zusätzlich
wurden Regressionstests für read-only Betrieb, relative Links in Unterordnern
und normalisierte Artikelart-Slugs ergänzt.
