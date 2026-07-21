# Document Quality Benchmark

Das Benchmark-Skript dient der kontinuierlichen Überwachung der Belegerkennung (Boundary Detection, Extraktion von Netto, Steuer, Brutto, Lieferant, Datum, etc.).

## Nutzung

```bash
python src/core/benchmark_document_pipeline.py data/testdata \
    --expected data/testdata/expected_benchmark.csv \
    --output data/reports/benchmark \
    --mode structural
```

### Modes

- `structural`: Keine LLM-Aufrufe. Evaluiert Regex, High-Priority-Dokumente und Boundary Detection.
- `fixture`: Für automatisierte Tests. Nutzt Mocking und künstliche Seiten.
- `live`: Verwendet LLM-Aufrufe. Beachtet `LLM_UNAVAILABLE` wenn das LLM nicht erreichbar ist.

### CSV Format (Ground Truth)

Die `--expected` CSV Datei verwendet UTF-8-BOM, Semikolon (`;`) als Trennzeichen, und unterstützt beliebige Dezimalformate.

Erwartete Spalten:
- `dateiname`
- `startseite`
- `endseite`
- `dokumenttyp`
- `lieferant`
- `datum`
- `rechnungsnummer`
- `netto`
- `steuer`
- `brutto`

### Output

Die Berichte werden unter `--output` (Standard: `data/reports/benchmark`) generiert:
- `benchmark_results.csv`: Detaillierte Liste der erkannten Dokumente mit ihren Werten.
- `benchmark_summary.json`: Metriken im JSON Format.
- `benchmark_report.md`: Übersichtlicher Bericht der Metriken.

### Metriken

- **Exact Boundary Precision / Recall**: Erkennung von exakten Start- und Endseiten-Paaren.
- **Start / End Page Accuracy**: Erkennung einzelner korrekter Start-/Endseiten.
- **Page Assignment Accuracy**: Anteil der korrekt den richtigen Dokumenten zugeordneten Seiten.
- **Net / Tax / Gross Amount Accuracy**: Anteil der korrekten Geldbeträge innerhalb einer Toleranz von 0,02 EUR.
- **Supplier / Document Type / Invoice Number Hit Rate**: Erkennungsquote für Strings (Case-Insensitive).
