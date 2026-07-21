# Adaptive Fast Lane

Der Adaptive Fast Lane Router ist ein deterministischer Router, der pro getrenntem Beleg entscheidet, welche Verarbeitungsschritte erforderlich sind. Er führt keine externen Aufrufe oder OCR durch, sondern wertet ausschließlich strukturierte Eingabeergebnisse aus.

## Routen

* **FAST_LANE**: Deterministische Extraktion ist ausreichend. Es sind keine LLM-Aufrufe nötig.
* **TARGETED_LLM**: Ein Großteil der Daten ist sicher erkannt, aber spezifische, klar benennbare Felder fehlen. Nur diese Felder werden an die KI übergeben.
* **FULL_LLM**: Mehrere zentrale Felder fehlen oder das Dokumentenlayout ist komplex/unbekannt.
* **MANUAL_REVIEW**: Harte Blockaden (z.B. geschützte Dokumenttypen, schwache OCR, Konflikte, Dubletten). Erfordert menschliche Prüfung.
* **REJECTED**: Beschädigte oder leere Eingabe, kann nicht verarbeitet werden.

## Routing-Priorität (Regeln)

Die Regeln werden zwingend in dieser Reihenfolge ausgewertet:

### A. REJECTED
* `input_valid == false`
* Beschädigte Eingabe, keine Seiten oder expliziter Eingabefehler.

### B. MANUAL_REVIEW
* **Geschützter Dokumenttyp**: (Kontoauszug, Bankdokument, Lieferschein, Angebot, Mahnung, Zahlungserinnerung, Vertrag, Versicherung, Steuerbescheid, Unlesbar)
* **Schwache OCR/Boundary**: `ocr_quality_score < 0.70` oder `boundary_confidence < 0.70`
* **Konflikte**: Boundary-Konflikt, Betragskonflikt, Währungskonflikt
* **Dublettenwarnung**: `duplicate_warning == true`
* **Dokumenttyp unklar**: Widersprüchlicher Dokumenttyp, `AMBIGUOUS` oder `INSUFFICIENT_TEXT`

### C. FAST_LANE
Nur wenn **alle** der folgenden Bedingungen erfüllt sind:
* `ocr_quality_score >= 0.85`
* `boundary_confidence >= 0.90`
* Dokumenttyp ist `CLASSIFIED` und Confidence `>= 0.90` (Typ `Rechnung` oder `Gutschrift`)
* Lieferant eindeutig (`found == true`, Confidence `>= 0.90`, keine Konflikte, nicht `UNKNOWN`)
* Rechnungsnummer eindeutig (`found == true`, Confidence `>= 0.90`, keine Konflikte, nicht `UNKNOWN/UNBEKANNT/REG-EXPR`)
* Beträge mathematisch korrekt (`math_valid == true`, `math_difference <= 0.02`, `net`, `tax` und `gross` vorhanden, Confidence `>= 0.90`, keine Konflikte)
* Keine Dublettenwarnung

### D. TARGETED_LLM
Wenn keine harte Blockade vorliegt und:
* `ocr_quality_score >= 0.75`
* `boundary_confidence >= 0.80`
* **Höchstens zwei** klar benennbare Felder fehlen (z.B. Lieferant, Rechnungsnummer, Netto, Steuer, Brutto).
* Die vorhandenen Werte widersprechen sich nicht.

### E. FULL_LLM
Wenn keine harte Blockade vorliegt und:
* Mindestens **drei** zentrale Felder fehlen oder deterministische Extraktion weitgehend unvollständig ist.

## Confidence-Berechnung

Es wird kein einfacher Durchschnitt verwendet. Eine schwache Sicherheitskomponente darf nicht verdeckt werden:

* **FAST_LANE**: Minimum aus OCR, Boundary und allen relevanten Feld-Confidences.
* **TARGETED_LLM / FULL_LLM**: Minimum der vorhandenen relevanten Evidenzen minus einem Abschlag von `0.10` je fehlendem zentralen Feld (begrenzt auf 0.0 bis 1.0).
* **MANUAL_REVIEW / REJECTED**: Beschreibt die Sicherheit der Routingentscheidung, nicht die Qualität des Belegs.

## Metriken & Schätzungen

Für LLM-Routen werden die benötigten Token und die Dauer geschätzt basierend auf der Konfiguration des Routers.

* `CHARS_PER_TOKEN = 4`
* `PROMPT_OVERHEAD_TOKENS = 250`
* `TOKENS_PER_REQUESTED_FIELD = 80`
* `DEFAULT_TOKENS_PER_SECOND = 20.0`

Für die Einsparungsberechnung bei Batch-Verarbeitungen (`route_batch`) wird eine Baseline von `50.0 Sekunden` (`baseline_llm_seconds_per_document`) pro Dokument angenommen, wenn ein LLM-Aufruf durch FAST_LANE vermieden wird.