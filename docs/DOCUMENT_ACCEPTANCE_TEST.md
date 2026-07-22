# Abnahmetest mit 120 Dokumenten

Der Test erfolgt erst nach der Wiki-Kompaktierung und verwendet ausschließlich
Kopien der Testdokumente. Bereits bearbeitete Produktionsdateien werden nicht
erneut verschoben oder umbenannt.

## Stichprobe

- 30 normale Lieferantenrechnungen
- 20 Belege wiederkehrender Lieferanten
- 15 Bankdokumente, insbesondere Commerzbank
- 15 schlechte Scans, Fotos oder gedrehte Seiten
- 10 mehrseitige beziehungsweise zusammengefügte PDFs
- 10 Gutschriften, Lieferscheine und Sondertypen
- 10 bekannte oder künstlich erzeugte Dubletten
- 10 unbekannte oder besonders schwierige Dokumente

Zuerst werden 30 Dokumente als Pilot verarbeitet. Nach der Fehlerkorrektur folgen
die übrigen 90 als unveränderte Abnahmemenge.

## Ground Truth

Die Erwartungs-CSV verwendet UTF-8-BOM und Semikolon. Pflichtfelder:

```text
dateiname;startseite;endseite;dokumenttyp;lieferant;datum;rechnungsnummer;netto;steuer;brutto;contact_entity_id;duplicate_of
```

`duplicate_of` bleibt bei einem Original leer und enthält bei einer Dublette die
Beleg-ID beziehungsweise den Dateinamen des Originals.

## Abnahmekriterien

- kein Dokument geht ohne sichtbaren Fehlerstatus verloren;
- 100 % der abgeschlossenen Belege sind in SQLite und FTS persistent;
- 100 % der PDF-Links der abgeschlossenen Belege sind auflösbar;
- keine neue Einzelbelegseite erscheint als aktiver Wiki-Node;
- Wiederholungsimporte erzeugen weder Kontakt- noch Quellenzeilen-Dubletten;
- Lieferanten-, Betrags-, Boundary- und Dokumenttypqualität werden über
  `benchmark_document_pipeline.py` ausgewiesen;
- RAG-Tests prüfen Top-1, Top-3 und Top-5 für Lieferant, Rechnungsnummer,
  Warengruppe, Zeitraum und Kontierung;
- ein Lieferantenname liefert zuerst die verdichtete Hubseite und danach die
  dazugehörigen Einzelbelege;
- ungeklärte Lieferanten landen in einer gemeinsamen Prüfseite und werden nicht
  automatisch als neue Entität gelernt.

## Befehle

```bash
python src/core/benchmark_document_pipeline.py data/testdata \
  --expected data/testdata/expected_benchmark.csv \
  --output data/reports/benchmark \
  --mode live
```

Der Ergebnisordner enthält CSV, JSON und Markdown. Vor der endgültigen Freigabe
werden Pilot- und Abnahmelauf separat archiviert und miteinander verglichen.
