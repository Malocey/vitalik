# Hybride Streaming-Architektur V2 (Konzept)

Dieses Design Document beschreibt den geplanten Umbau der Dokumentenverarbeitung, um Abstürze bei großen Scans (z.B. 160 Seiten) zu verhindern, die Performance massiv zu steigern und das LLM durch ein lernfähiges, lokales Skript-Routing zu entlasten.

## 1. Problemstellung der aktuellen Architektur
Aktuell lädt die `PDFEngine` ein gesamtes PDF in den Speicher und startet parallele OCR-Prozesse (Tesseract) für alle Seiten. Bei großen Dokumenten führt dies zu RAM-Erschöpfung, Thread-Konflikten und Abstürzen. Zudem wird das LLM oft auch für Standard-Lieferanten aufgerufen, deren Layout längst bekannt sein sollte.

## 2. Lösungsansatz: Sliding Window & Hybrides Routing

### 2.1 Sliding Window Scanning (Streaming)
Anstatt 160 Seiten auf einmal zu scannen, nutzt das System ein **Sliding Window** (z.B. 3 Dokumente bzw. ca. 10 Seiten voraus).
1. Der Scanner liest die ersten Seiten und versucht on-the-fly die Beleggrenzen zu erkennen.
2. Sobald ein Beleg zerschnitten ist (Dokument 1), wird er an die Verarbeitung (Schritt 2.2) geschickt.
3. Der freigewordene Platz im Window wird genutzt, um Dokument 4 nachzuscannen.
4. **Vorteil:** Der Arbeitsspeicher bleibt extrem konstant und Tesseract-Instanzen werden sauber dosiert (max. 2-4 Threads gleichzeitig).

### 2.2 Lernfähige Skript-Erkennung (Datenbank)
Es wird eine lokale SQLite-Datenbanktabelle eingeführt (z.B. `layout_memory`), die sich Layout-Muster, Absender-Schlüsselwörter und Seitengrenzen von bekannten Lieferanten merkt.
- Die Belege durchlaufen zuerst das deterministische Skript.
- Findet das Skript das Layout in der Datenbank und kann alle Felder (Rechnungsnummer, Betrag) mit hoher Confidence extrahieren, ist das Dokument "fertig".

### 2.3 LLM als intelligenter Fallback
- Nur wenn die Confidence des Skripts zu niedrig ist (z.B. neues Layout, unleserlicher Scan), wird der zerschnittene Beleg an das lokale KI-Modell (LLM) übergeben.
- Das LLM extrahiert die Daten.
- **Lernschleife:** Nach erfolgreicher KI-Verarbeitung analysiert das System, woran das Skript gescheitert ist, und updatet die `layout_memory`-Datenbank. Beim nächsten Mal wird dieser Lieferant vom Skript erkannt.

## 3. Umsetzungsschritte (To-Do für den nächsten Branch)
1. `ocr_engine.py` härten: `OMP_THREAD_LIMIT=1` erzwingen, `with Image.open()` nutzen und Bilder vor der OCR skalieren (Memory Leaks fixen).
2. `pdf_engine.py` umbauen: Iterator-basiertes Streaming statt Listen-Extraktion implementieren.
3. `boundary_detector_v2.py` in den Stream einhängen.
4. `layout_memory` in SQLite anlegen und die Feedback-Schleife aus der `ArchivePipeline` dorthin verbinden.
