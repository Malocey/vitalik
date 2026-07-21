# Multi-Format Ingestion Engine

Stand: 22. Juli 2026

Das Modul `src/parser/multi_format_engine.py` erweitert das System von reinen PDF- und Bilddateien auf ein universelles Multi-Format-Dokumentenmanagement.

## Unterstützte Dateiformate

| Format | Dateiendung | Parsing-Methode | Extraktion & Formatierung |
|---|---|---|---|
| PDF | `.pdf` | `pdf_engine.py` | Seitenweise Text-Layer- und OCR-Inspektion |
| Bilder | `.png`, `.jpg`, `.jpeg` | `ocr_engine.py` | 300 DPI Tesseract OCR mit Qualitätsbewertung |
| Word | `.docx`, `.doc` | `python-docx` | Absätze, Überschriften und Markdown-Tabellen |
| Excel | `.xlsx`, `.xls` | `openpyxl` | Tabellenblattweise Extraktion als Markdown-Tabellen |
| CSV | `.csv` | `csv` (Standard-Bibliothek) | Strukturierte Markdown-Tabellen |
| E-Mails | `.eml`, `.msg` | `email` / `extract_msg` | Header (From, To, Subject, Date) & Textkörper |
| Text | `.txt`, `.md` | `read_text` | Direkter Text-Import |

## Integration in die Pipeline

1. **`MultiFormatEngine.extract_document(file_path)`**: Konvertiert jede beliebige unterstützte Datei in einheitliche Seiten-Objekte (`page_num`, `text_snippet`, `full_text`, `ocr_status`, `ocr_confidence`).
2. **Dashboard Scanner (`dashboard_server.py`)**: Scannt Ordner nach allen 13 unterstützten Endungen.
3. **Fast Lane & RAG**: Extrahierte Tabellen und Texte fließen direkt in den `FastLaneRouter`, SQLite-FTS5 und das Karpathy Wiki.
