# Jules-Auftrag: Aussagekräftiger RAG-/Wiki-Graph mit Connections

Arbeite in einem eigenen Branch `feature/rag-graph-connections`. Verändere keine
produktiven Dateien unter `data/wiki` und keine SQLite-Inhalte. Die Umsetzung
muss mit temporären Fixtures vollständig lokal testbar sein.

## Ziel

Der Graph soll nicht nur leere Kästen beziehungsweise Name und Kategorie zeigen.
Jeder Node soll die wichtigsten strukturierten Informationen und sinnvolle,
nachvollziehbare Beziehungen darstellen. Das aktive Wiki bleibt verdichtet:
keine neuen Einzelartikel-Nodes und keine aktiven Einzelbeleg-Nodes.

## Backend

1. Mache `GET /api/wiki` rekursiv über `data/wiki/**/*.md`.
2. Schließe `index.md`, `log.md` und jeden Pfadbestandteil `archive` aus.
3. Verwende stabile, kollisionsfreie Node-IDs. Bei gleichen Dateinamen in
   unterschiedlichen Ordnern darf keine Seite überschrieben werden.
4. Parse Frontmatter ausschließlich mit `yaml.safe_load`; unterstütze die
   vorhandenen Legacy-Seiten ohne Frontmatter read-only.
5. Erweitere `get_graph_data()` um Node-Metadaten wie `entity_type`, Kurzfassung,
   Rollen, Ort/Land, sevDesk-ID, Debitor/Kreditor, Artikelarten, SKR03-Konten,
   Belegquellenanzahl, Prüfstatus und relativen Wiki-Pfad. Leere Werte nicht als
   `None`-Text darstellen.
6. Erzeuge typisierte Edges mit `relation` und optional `evidence`, mindestens:
   Kontakt -> Kontaktart, Lieferant -> Artikelart, Lieferant -> SKR03-Konto,
   Lieferant -> Quellenbeleg/Beleg-ID und Wissensgraph -> Kategorie.
7. Beleg-Connections dürfen aus SQLite `belege` read-only ergänzt werden.
   Nutze eine injizierbare `db_path` und SQLite-URI `mode=ro`. Keine Datenbank
   darf beim Lesen automatisch erzeugt werden.
8. Keine Connections aus unsicherer Namensähnlichkeit erfinden. Nur explizite
   Wikilinks, Frontmatter, starke IDs oder belegte SQLite-Felder verwenden.

## Darstellung

1. Ergänze Farben und Legende für Lieferanten, Kunden, Artikelarten,
   Bankdokumente, Prüfqueue und Systemwissen.
2. Zeige beim Anklicken eines Nodes die Metadaten und den Markdown-Inhalt aus
   Unterordnern zuverlässig an.
3. Zeige den Beziehungstyp an der Kante beziehungsweise im Detailbereich.
4. Biete Filter für Node-Typ, Lieferant/Kunde, Artikelart und Prüfstatus sowie
   eine Suche nach Name, ID und Rechnungsnummer.
5. Große Graphen müssen bedienbar bleiben: initial Kategorie-/Hub-Nodes zeigen
   und Detailverbindungen bei Auswahl oder Filter einblenden. Keine 70
   Einzelbelege ungefiltert auf einmal rendern.
6. HTML-Inhalte sicher als Text rendern; keine unbereinigte Markdown- oder
   Frontmatter-Ausgabe über `innerHTML`.

## Tests und Abnahme

Erstelle beziehungsweise erweitere Pytest-Tests für:

- rekursive Seitenfindung und Archivausschluss;
- zwei gleichnamige Dateien in verschiedenen Unterordnern;
- Frontmatter und Legacy-Seite;
- Node-Metadaten ohne `None`-Platzhalter;
- alle geforderten Edge-Typen;
- fehlende oder nicht lesbare SQLite-Datenbank;
- keinerlei Schreibzugriff auf Wiki oder SQLite;
- keine erfundenen Edges bei bloß ähnlichen Namen;
- API-Test für einen Kontakt aus `entities/contacts` und einen Lieferanten-Hub;
- Frontend-Test oder klar isolierbarer JavaScript-Test für Auswahl, Filter und
  sichere Textdarstellung.

Führe anschließend den vollständigen Testbestand aus und dokumentiere vorher/
nachher: Node-Anzahl, Edge-Anzahl, Nodes mit Detailinhalt, Verteilung der
Edge-Typen und Seiten ohne auflösbaren Detailinhalt. Liefere keine generierten
Produktivberichte oder Dateien aus `data/` im Commit mit.
