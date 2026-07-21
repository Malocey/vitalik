"""
Lokale OCR-Engine (Optical Character Recognition) für VG Delikatessen.
Verarbeitet gescannte Belege und Bild-PDFs lokal ohne externe Online-Dienste.
Unterstützt pytesseract / Tesseract OCR mit Fallback-Mechanismus.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

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

    def extract_with_quality(self, image_path: Path, lang: str = "deu+eng") -> Dict[str, Any]:
        """OCR mit messbarer Wortkonfidenz; erzeugt niemals synthetischen Inhalt."""
        result = {"text": "", "confidence": 0.0, "status": "OCR_FAILED"}
        if not image_path.exists():
            logger.error(f"[OCR ERROR] Datei nicht gefunden: {image_path}")
            return result
        if not HAS_PYTESSERACT:
            logger.error("[OCR ERROR] pytesseract/Tesseract ist nicht verfügbar.")
            return result
        try:
            img = Image.open(image_path)
            data = pytesseract.image_to_data(
                img, lang=lang, output_type=pytesseract.Output.DICT
            )
            words = []
            confidences = []
            for word, confidence in zip(data.get("text", []), data.get("conf", [])):
                word = str(word).strip()
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    confidence = -1
                if word:
                    words.append(word)
                    if confidence >= 0:
                        confidences.append(confidence)
            text = " ".join(words)
            score = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
            status = "OCR_OK" if score >= 0.70 and len(text) >= 20 else "OCR_WEAK"
            logger.info(
                f"[OCR] {len(text)} Zeichen, Qualität {score:.2f} aus {image_path.name}."
            )
            return {"text": text, "confidence": round(score, 4), "status": status}
        except Exception as exc:
            logger.exception(f"[OCR ERROR] Texterkennung fehlgeschlagen: {exc}")
            return result

    def extract_text_from_image(self, image_path: Path, lang: str = "deu+eng") -> str:
        """
        Führt eine OCR-Texterkennung auf einer Bilddatei (PNG, JPG, TIFF) aus.
        """
        return self.extract_with_quality(image_path, lang=lang)["text"]


# Globale OCR-Instanz
ocr_engine = OCREngine()
