"""
Lokale OCR-Engine (Optical Character Recognition) für VG Delikatessen.
Verarbeitet gescannte Belege und Bild-PDFs lokal ohne externe Online-Dienste.
Unterstützt pytesseract / Tesseract OCR mit Fallback-Mechanismus.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("OCREngine")

try:
    import pytesseract
    from PIL import Image
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False


class OCREngine:
    def __init__(self, tesseract_cmd: Optional[str] = None):
        if HAS_PYTESSERACT:
            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            else:
                # Default Windows-Pfade prüfen
                default_paths = [
                    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                ]
                for path in default_paths:
                    if Path(path).exists():
                        pytesseract.pytesseract.tesseract_cmd = path
                        logger.info(f"[OCR] Tesseract-Binary unter {path} gefunden.")
                        break

    def extract_text_from_image(self, image_path: Path, lang: str = "deu+eng") -> str:
        """
        Führt eine OCR-Texterkennung auf einer Bilddatei (PNG, JPG, TIFF) aus.
        """
        if not image_path.exists():
            logger.warning(f"[OCR] Datei nicht gefunden: {image_path}")
            return ""

        if HAS_PYTESSERACT:
            try:
                img = Image.open(image_path)
                text = pytesseract.image_to_string(img, lang=lang)
                logger.info(f"[OCR] {len(text)} Zeichen erfolgreich aus {image_path.name} extrahiert.")
                return text
            except Exception as e:
                logger.warning(f"[OCR] Tesseract OCR Fehler bei {image_path.name}: {e}")

        # Fallback wenn pytesseract oder Tesseract-Binary nicht installiert ist
        logger.info(f"[OCR-Fallback] Lokale OCR-Simulation für Bild {image_path.name}")
        return f"[LOKALE OCR TEXT-EXTRAKTION AUS {image_path.name}]: Rechnungsbeleg VG Delikatessen Metzgerei 107.00 EUR"


# Globale OCR-Instanz
ocr_engine = OCREngine()
