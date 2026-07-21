"""
Multi-Format Extraction Engine für VG Delikatessen.
Unterstützt PDF, PNG, JPG, TXT, MD, DOCX, XLSX, CSV, EML und MSG.
Extrahierte Inhalte werden einheitlich in Seiten-/Abschnitts-Strukturen überführt.
"""

import email
import json
import logging
import os
import re
from email import policy
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("MultiFormatEngine")


class MultiFormatEngine:
    SUPPORTED_EXTENSIONS = {
        ".pdf", ".png", ".jpg", ".jpeg", ".txt", ".md",
        ".docx", ".doc", ".xlsx", ".xls", ".csv", ".eml", ".msg"
    }

    def is_supported(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def extract_document(self, file_path: Path) -> List[Dict[str, Any]]:
        """
        Liest eine beliebige unterstützte Datei aus und gibt eine Liste von Seiten-Dicts zurück.
        """
        ext = file_path.suffix.lower()
        if ext == ".pdf":
            from src.parser.pdf_engine import pdf_engine
            return pdf_engine.inspect_pdf(file_path)
        elif ext in [".png", ".jpg", ".jpeg"]:
            from src.parser.ocr_engine import ocr_engine
            ocr_res = ocr_engine.perform_ocr(file_path)
            text = ocr_res.get("text", "")
            conf = (ocr_res.get("confidence", 0.0) or 0.0) / 100.0
            return [{
                "page_num": 1,
                "text_snippet": text[:500],
                "full_text": text,
                "ocr_status": "IMAGE_OCR",
                "ocr_confidence": conf
            }]
        elif ext in [".txt", ".md"]:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            return [{
                "page_num": 1,
                "text_snippet": text[:500],
                "full_text": text,
                "ocr_status": "PLAIN_TEXT",
                "ocr_confidence": 1.0
            }]
        elif ext == ".docx":
            return self._extract_docx(file_path)
        elif ext in [".xlsx", ".xls", ".csv"]:
            return self._extract_spreadsheet(file_path)
        elif ext in [".eml", ".msg"]:
            return self._extract_email(file_path)
        else:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            return [{
                "page_num": 1,
                "text_snippet": text[:500],
                "full_text": text,
                "ocr_status": "UNKNOWN_TEXT",
                "ocr_confidence": 1.0
            }]

    def _extract_docx(self, file_path: Path) -> List[Dict[str, Any]]:
        try:
            import docx
            doc = docx.Document(str(file_path))
            full_text = []
            for para in doc.paragraphs:
                if para.text.strip():
                    full_text.append(para.text)
            
            # Format tables inside docx into Markdown
            for table in doc.tables:
                table_lines = []
                for row in table.rows:
                    cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    table_lines.append("| " + " | ".join(cells) + " |")
                if table_lines:
                    full_text.append("\n".join(table_lines))
                    
            combined = "\n\n".join(full_text)
            return [{
                "page_num": 1,
                "text_snippet": combined[:500],
                "full_text": combined,
                "ocr_status": "DOCX",
                "ocr_confidence": 1.0
            }]
        except Exception as e:
            logger.warning(f"[MultiFormatEngine] Fehler beim Lesen von DOCX {file_path.name}: {e}")
            return [{
                "page_num": 1,
                "text_snippet": f"Fehler beim DOCX-Lesen: {e}",
                "full_text": "",
                "ocr_status": "DOCX_ERROR",
                "ocr_confidence": 0.0
            }]

    def _extract_spreadsheet(self, file_path: Path) -> List[Dict[str, Any]]:
        ext = file_path.suffix.lower()
        pages = []
        try:
            if ext == ".csv":
                import csv
                lines = []
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.reader(f)
                    for row in reader:
                        lines.append("| " + " | ".join(row) + " |")
                text = "\n".join(lines)
                pages.append({
                    "page_num": 1,
                    "text_snippet": text[:500],
                    "full_text": text,
                    "ocr_status": "CSV",
                    "ocr_confidence": 1.0
                })
            else:
                import openpyxl
                wb = openpyxl.load_workbook(file_path, data_only=True)
                for idx, sheet_name in enumerate(wb.sheetnames, 1):
                    sheet = wb[sheet_name]
                    sheet_lines = [f"=== SHEET: {sheet_name} ==="]
                    for row in sheet.iter_rows(values_only=True):
                        if any(row):
                            cells = [str(val) if val is not None else "" for val in row]
                            sheet_lines.append("| " + " | ".join(cells) + " |")
                    text = "\n".join(sheet_lines)
                    pages.append({
                        "page_num": idx,
                        "text_snippet": text[:500],
                        "full_text": text,
                        "ocr_status": "EXCEL",
                        "ocr_confidence": 1.0
                    })
        except Exception as e:
            logger.warning(f"[MultiFormatEngine] Fehler beim Lesen von Excel/CSV {file_path.name}: {e}")
            pages.append({
                "page_num": 1,
                "text_snippet": f"Fehler beim Tabelle-Lesen: {e}",
                "full_text": "",
                "ocr_status": "EXCEL_ERROR",
                "ocr_confidence": 0.0
            })
        return pages

    def _extract_email(self, file_path: Path) -> List[Dict[str, Any]]:
        ext = file_path.suffix.lower()
        if ext == ".msg":
            try:
                import extract_msg
                msg = extract_msg.Message(str(file_path))
                text = f"From: {msg.sender}\nTo: {msg.to}\nSubject: {msg.subject}\nDate: {msg.date}\n\n{msg.body}"
                return [{
                    "page_num": 1,
                    "text_snippet": text[:500],
                    "full_text": text,
                    "ocr_status": "EMAIL_MSG",
                    "ocr_confidence": 1.0
                }]
            except Exception as e:
                logger.warning(f"[MultiFormatEngine] MSG Fallback für {file_path.name}: {e}")

        # Standard .eml parsing
        try:
            raw_bytes = file_path.read_bytes()
            msg = email.message_from_bytes(raw_bytes, policy=policy.default)
            headers = [
                f"From: {msg.get('from', '')}",
                f"To: {msg.get('to', '')}",
                f"Subject: {msg.get('subject', '')}",
                f"Date: {msg.get('date', '')}"
            ]
            body_parts = []
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type in ["text/plain", "text/html"]:
                        payload = part.get_content()
                        if isinstance(payload, str):
                            body_parts.append(payload)
            else:
                body_parts.append(msg.get_content() or "")

            combined_body = "\n".join(body_parts)
            text = "\n".join(headers) + "\n\n" + combined_body
            return [{
                "page_num": 1,
                "text_snippet": text[:500],
                "full_text": text,
                "ocr_status": "EMAIL_EML",
                "ocr_confidence": 1.0
            }]
        except Exception as e:
            logger.warning(f"[MultiFormatEngine] Fehler beim Lesen von E-Mail {file_path.name}: {e}")
            return [{
                "page_num": 1,
                "text_snippet": f"Fehler beim E-Mail-Lesen: {e}",
                "full_text": "",
                "ocr_status": "EMAIL_ERROR",
                "ocr_confidence": 0.0
            }]


multi_format_engine = MultiFormatEngine()
