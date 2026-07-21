# Document Type Classifier

Der `DocumentTypeClassifier` ist ein offline-fähiger, regelbasierter Klassifikator für Dokumente. Er benötigt keine Netzwerkaufrufe oder Machine Learning-Inferenz und analysiert stattdessen den extrahierten Text.

## Funktionsweise

Der Classifier berechnet für jeden Dokumenttyp (z.B. Rechnung, Lieferschein, Kontoauszug) einen Score:
`Score = Summe(Positiv-Gewichte) - Summe(Negativ-Gewichte)`
Dieser Score wird auf den Bereich `0.0` bis `1.0` begrenzt.

Die Gewichte sind feste, transparente Konstanten im Code (0.8 = STARK, 0.4 = MITTEL, 0.2 = SCHWACH).

## Features

- **Erkennung von "Unlesbar":** Wenn der Text zu wenig alphanumerische Zeichen oder zu wenig sinnvolle Wörter enthält, wird er als "Unlesbar" eingestuft (`INSUFFICIENT_TEXT`).
- **AMBIGUOUS-Status:** Wenn die zwei wahrscheinlichsten Dokumenttypen in ihrem Score nah beieinander liegen (Differenz < 0.15), wird der Status auf `AMBIGUOUS` gesetzt, um anzuzeigen, dass manuelle Klärung nötig ist. Die konkurrierenden Typen werden im Feld `conflicting_types` dokumentiert.
- **Bankdokument-Schutz:** Dokumente mit bankrelevanten Merkmalen (z.B. Kontonummer, IBAN, Buchungsdatum) sammeln Punkte in der Klasse Kontoauszug / Bankdokument. Diese Klassen blockieren automatisch das Flag `automatic_booking_allowed`.
- **Automatische Buchung:** `automatic_booking_allowed` wird ausschließlich bei der eindeutigen Klassifikation (Konfidenz >= 0.90) von Rechnungen und Gutschriften gesetzt, vorausgesetzt, es liegen keine konfliktierenden Signale (z. B. von Verträgen, Banken oder Lieferscheinen) vor.

## Bekannte Einschränkungen

- **Reine Regelbasis:** Komplexe grammatikalische Zusammenhänge werden nicht verstanden, lediglich Stichworte und reguläre Ausdrücke werden herangezogen.
- **Textextraktion:** Es wird vorausgesetzt, dass vorgeschaltete OCR- oder PDF-Parser vernünftigen Text liefern. Fehler bei der optischen Zeichenerkennung werden nur rudimentär korrigiert.
- **Kombinierte Dokumente:** Wenn ein PDF sowohl eine Rechnung als auch Lieferschein und Vertrag enthält, wertet der Klassifikator Signale aller enthaltenen Dokumente aus, was zwangsläufig zum `AMBIGUOUS`-Status führt, da die automatische Buchung aus Sicherheitsgründen blockiert wird.
