# Rechnungs-Matching & Lieferanten-Preisentwicklungs-Monitor

Stand: 22. Juli 2026

## 1. Rechnungs- & Lieferschein-Matching Engine (`matching_engine.py`)

Das Modul `src/core/matching_engine.py` gleicht Lieferscheine (`Lieferschein`) und Eingangsrechnungen (`Rechnung`) automatisiert ab.

### Funktionsweise
- **Identitäts- & Lieferantenabgleich**: Nutzt das deduplizierte `ContactMemory`, um Dokumente demselben Lieferanten zuzuordnen.
- **Datumsfenster**: Berücksichtigt ein flexibles Zeitfenster (±30 Tage).
- **Diskrepanzerkennung**: 
  - `MATCHED` (Score: 0,95): Lieferant, Daten und Beträge stimmen überein.
  - `DISCREPANCY` (Score: 0,70): Betrags- oder Lieferantenabweichungen werden protokolliert.
  - `OFFEN_KEIN_LIEFERSCHEIN`: Rechnung liegt vor, aber noch kein Lieferschein im System.
- **SQLite-Tabelle**: `beleg_matches` in `data/rag_index.db`.

---

## 2. Lieferanten-Preisentwicklungs & Inflations-Monitor (`price_monitor.py`)

Das Modul `src/core/price_monitor.py` verfolgt Einzelpreise pro Artikel über verschiedene Belege, Excel-Preislisten (`.xlsx`) und Angebote (`.docx`) hinweg.

### Funktionsweise
- **Preishistorie**: Erfasst `(supplier_name, item_name, unit_price, unit_name, recorded_at)` in der SQLite-Tabelle `item_price_history`.
- **Preistrend-Berechnung**:
  $$\text{Preisveränderung \%} = \frac{\text{Aktueller Preis} - \text{Erster Preis}}{\text{Erster Preis}} \times 100$$
- **Preiserhöhungs-Warnung**: Erreicht die Preissteigerung **> 2,0 %**, wird automatisch der Status `PREISERHOEHUNG_WARNUNG` gesetzt und im Dashboard hervorgehoben.
