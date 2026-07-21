# Beleg-Pipeline & 3-Stufen-Schutzschild
*Kategorie: workflow* | *Zuletzt aktualisiert: 2026-07-21*

### Workflow für Belegverarbeitung
1. **Scans & PDFs**: 100-seitige Stapel werden zerschnitten und per RAG, OCR & LLM analysiert.
2. **3-Stufen Schutzschild**:
   - Stufe 1: Mathematische Prüfung ($Netto + Steuer = Brutto$)
   - Stufe 2: Confidence-Check (< 95% -> Ordner `00_Manuelle_Prüfung_Nötig`)
   - Stufe 3: Telegram Bestätigungs-Buttons (`[Bestätigen]`, `[Prüfen]`)

### 🔗 Querverweise
- [lieferanten_und_kontenrahmen](./lieferanten_und_kontenrahmen.md)
