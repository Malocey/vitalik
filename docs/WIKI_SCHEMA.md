# Verbindliches Schema für das verdichtete LLM-Wiki

Das Wiki ist eine gepflegte Wissensschicht und kein zweites Belegarchiv. PDF und
OCR bleiben unveränderliche Quellen; vollständige Belegdaten liegen in SQLite.

## Regeln

1. Genau eine aktive Seite pro kanonischer Lieferanten- oder Kundenentität.
2. Ein Einzelbeleg ist eine Quellenzeile, kein Graph-Knoten.
3. Entitäten werden vorrangig über `contact_entity_id`, USt-ID, IBAN oder
   sevDesk-ID zusammengeführt; der normalisierte Name ist nur der Fallback.
4. Artikel werden innerhalb einer Artikelart zusammengefasst und erzeugen keine
   einzelnen Wiki-Nodes.
5. Nur verdichtete, belegte Erkenntnisse werden semantisch indiziert.
6. Vollständiger OCR-Text bleibt als nachrangiger FTS-Fallback verfügbar.
7. `log.md` ist append-only, wird aber nicht als Fachwissen indiziert.
8. Widersprüche werden markiert und nicht still überschrieben.
9. Jede Aussage muss über eine Beleg-ID und möglichst einen PDF-Link prüfbar sein.
10. Migrationen sind Dry-Run-first, sichern DB und Wiki und archivieren statt zu löschen.

## Aktive Verzeichnisse

- `entities/suppliers/`: Lieferanten-Hubseiten
- `entities/customers/`: Kunden-Hubseiten
- `entities/categories/`: Artikelarten und fachliche Kategorien
- `concepts/`: Regeln, Kontierung und andere verdichtete Erkenntnisse
- `archive/belege/`: alte Einzelbelegseiten; nicht im Index oder Graph

## Pflegeablauf

Neue Quelle → strukturierte Extraktion → Validierung → SQLite/FTS → kanonische
Entität bestimmen → bestehende Hubseite aktualisieren → Index aktualisieren →
genau einen Logeintrag schreiben → Persistenz prüfen.
