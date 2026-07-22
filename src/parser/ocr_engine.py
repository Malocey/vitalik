"""
Lokale OCR-Engine (Optical Character Recognition) für VG Delikatessen.
Verarbeitet gescannte Belege und Bild-PDFs lokal ohne externe Online-Dienste.
Unterstützt pytesseract / Tesseract OCR mit Fallback-Mechanismus.
"""

import logging
import hashlib
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional, List

logger = logging.getLogger("OCREngine")

try:
    import pytesseract
    from PIL import Image
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False


class OCREngine:
    def __init__(self, tesseract_cmd: Optional[str] = None):
        self._page_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._cache_lock = threading.Lock()
        self._cache_limit = 512
        if HAS_PYTESSERACT:
            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            else:
                default_paths = [
                    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                ]
                for path in default_paths:
                    if Path(path).exists():
                        pytesseract.pytesseract.tesseract_cmd = path
                        logger.info(f"[OCR] Tesseract-Binary unter {path} gefunden.")
                        break

    def _compute_md5(self, path: Path) -> str:
        try:
            digest = hashlib.md5()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except Exception:
            return str(path.name)

    def extract_with_quality(self, image_path: Path, lang: str = "deu+eng") -> Dict[str, Any]:
        """OCR mit MD5-Seitencache (0.00s bei bereits verarbeiteten Bildern)."""
        result = {"text": "", "confidence": 0.0, "status": "OCR_FAILED"}
        if not image_path.exists():
            logger.error(f"[OCR ERROR] Datei nicht gefunden: {image_path}")
            return result

        md5_hash = self._compute_md5(image_path)
        with self._cache_lock:
            cached = self._page_cache.get(md5_hash)
            if cached is not None:
                self._page_cache.move_to_end(md5_hash)
                logger.info(f"[OCR CACHE HIT] {image_path.name} aus MD5-Cache geladen.")
                return dict(cached)

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
            res = {"text": text, "confidence": round(score, 4), "status": status}
            with self._cache_lock:
                self._page_cache[md5_hash] = dict(res)
                self._page_cache.move_to_end(md5_hash)
                while len(self._page_cache) > self._cache_limit:
                    self._page_cache.popitem(last=False)
            return res
        except Exception as exc:
            logger.exception(f"[OCR ERROR] Texterkennung fehlgeschlagen: {exc}")
            res = {"text": "", "confidence": 0.0, "status": f"OCR_FAILED: {exc}"}
            return res

    def extract_batch_images_parallel(self, image_paths: List[Path], max_workers: int = 4) -> Dict[str, Dict[str, Any]]:
        """Verarbeitet mehrere Bilddateien parallel über CPU-Threads."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = {}
        if not image_paths:
            return results

        workers = min(max_workers, len(image_paths))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(self.extract_with_quality, p): str(p) for p in image_paths}
            for future in as_completed(future_map):
                p_str = future_map[future]
                try:
                    results[p_str] = future.result()
                except Exception as e:
                    results[p_str] = {"text": "", "confidence": 0.0, "status": f"OCR_ERROR: {e}"}
        return results

    def extract_text_from_image(self, image_path: Path, lang: str = "deu+eng") -> str:
        return self.extract_with_quality(image_path, lang=lang)["text"]


# Globale OCR-Instanz
ocr_engine = OCREngine()
