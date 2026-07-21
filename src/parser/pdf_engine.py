"""
PDF Engine für VG Delikatessen.
Verarbeitet große, unsortierte PDF-Scans mit pypdf und integriertem lokalen OCR-Fallback.
Extrahiert Seitentexte und zerschneidet Dokumente an den ermittelten Beleggrenzen.
"""

import logging
import hashlib
import json
from pathlib import Path
from typing import List, Dict, Any
from src.parser.ocr_engine import ocr_engine

logger = logging.getLogger("PDFEngine")

try:
    from pypdf import PdfReader, PdfWriter
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

try:
    import pypdfium2 as pdfium
    HAS_PDFIUM = True
except ImportError:
    HAS_PDFIUM = False


class PDFEngine:
    def __init__(self):
        pass

    def calculate_md5(self, file_path: Path) -> str:
        """Berechnet den MD5-Hash einer Datei."""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def inspect_pdf(self, pdf_path: Path) -> List[Dict[str, Any]]:
        """
        Liest alle Seiten eines PDFs ein. Wenn kein eingebetteter Text vorhanden ist (Scan-PDF),
        wird automatisch die lokale OCR-Engine aktiviert.
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF Datei nicht gefunden: {pdf_path}")

        if HAS_PYPDF:
            try:
                reader = PdfReader(str(pdf_path))
                total_pages = len(reader.pages)
                file_hash = self.calculate_md5(pdf_path)
                cache_dir = Path("data/ocr_cache") / file_hash
                cache_dir.mkdir(parents=True, exist_ok=True)
                
                from concurrent.futures import ThreadPoolExecutor
                
                def process_page(idx: int) -> Dict[str, Any]:
                    cache_path = cache_dir / f"page_{idx + 1:05d}.json"
                    if cache_path.exists():
                        try:
                            cached = json.loads(cache_path.read_text(encoding="utf-8"))
                            if cached.get("cache_version") == 1:
                                cached.pop("cache_version", None)
                                return cached
                        except (OSError, ValueError):
                            logger.warning(f"[OCR CACHE] Ungültiger Cache für Seite {idx + 1}; erneute OCR.")
                    try:
                        # Eigenen Reader pro Thread öffnen für Thread-Sicherheit
                        t_reader = PdfReader(str(pdf_path))
                        page = t_reader.pages[idx]
                        text = page.extract_text() or ""
                        used_ocr = False
                        qualities = []
                        
                        # Falls die Seite ein reiner Bildscan ist (wenig/kein Text), lokale OCR nutzen
                        if len(text.strip()) < 20:
                            used_ocr = True
                            logger.info(f"[PDFEngine] Seite {idx+1} enthält keinen eingebetteten Text. Starte lokale OCR (Parallel)...")
                            extracted_text = ""
                            # Ganze Seite rendern: zuverlässiger als einzelne PDF-Bildobjekte.
                            if HAS_PDFIUM:
                                temp_img_dir = Path("data/temp")
                                temp_img_dir.mkdir(parents=True, exist_ok=True)
                                temp_img_path = temp_img_dir / f"temp_page_{idx}_{pdf_path.stem}.png"
                                try:
                                    pdf_doc = pdfium.PdfDocument(str(pdf_path))
                                    rendered = pdf_doc[idx].render(scale=300 / 72).to_pil()
                                    rendered.save(temp_img_path, format="PNG")
                                    ocr_result = ocr_engine.extract_with_quality(temp_img_path)
                                    extracted_text = ocr_result["text"]
                                    qualities.append(ocr_result["confidence"])
                                finally:
                                    if temp_img_path.exists():
                                        temp_img_path.unlink()
                            elif hasattr(page, "images") and len(page.images) > 0:
                                logger.warning(
                                    "[PDFEngine] pypdfium2 fehlt; nutze weniger robusten Bildobjekt-Fallback."
                                )
                                for img_idx, img_obj in enumerate(page.images):
                                    temp_img_dir = Path("data/temp")
                                    temp_img_dir.mkdir(parents=True, exist_ok=True)
                                    temp_img_path = temp_img_dir / f"temp_img_{idx}_{img_idx}_{pdf_path.stem}.png"
                                    try:
                                        temp_img_path.write_bytes(img_obj.data)
                                        ocr_result = ocr_engine.extract_with_quality(temp_img_path)
                                        if ocr_result["text"]:
                                            extracted_text += "\n" + ocr_result["text"]
                                            qualities.append(ocr_result["confidence"])
                                    finally:
                                        if temp_img_path.exists():
                                            temp_img_path.unlink()
                            
                            if extracted_text.strip():
                                text = extracted_text.strip()
                            else:
                                logger.info(f"[PDFEngine] Keine extrahierbaren Texte auf Seite {idx+1} gefunden.")
                                text = ""
                        
                        result = {
                            "page_num": idx + 1,
                            "text_snippet": text[:500],
                            "full_text": text,
                            "ocr_confidence": round(sum(qualities) / len(qualities), 4) if used_ocr and qualities else (1.0 if not used_ocr else 0.0),
                            "ocr_status": ("OCR_OK" if qualities and sum(qualities) / len(qualities) >= 0.70 else "OCR_WEAK") if used_ocr else "TEXT_LAYER",
                        }
                        temporary = cache_path.with_suffix(".tmp")
                        temporary.write_text(json.dumps({"cache_version": 1, **result}, ensure_ascii=False), encoding="utf-8")
                        temporary.replace(cache_path)
                        return result
                    except Exception as pe:
                        logger.warning(f"[PDFEngine] Fehler bei Seite {idx+1} in Parallel-OCR: {pe}")
                        return {
                            "page_num": idx + 1,
                            "text_snippet": "",
                            "full_text": "", "ocr_confidence": 0.0,
                            "ocr_status": "OCR_FAILED",
                        }
                
                # Mit ThreadPoolExecutor parallel verarbeiten (bis zu 8 Threads)
                max_workers = min(8, total_pages)
                logger.info(f"[PDFEngine] Starte paralleles OCR mit {max_workers} Workern für {total_pages} Seiten...")
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    results = list(executor.map(process_page, range(total_pages)))
                
                # Sortieren nach Seitennummer
                results = sorted(results, key=lambda x: x["page_num"])
                return results
            except Exception as e:
                logger.exception(f"[PDFEngine ERROR] PDF-Verarbeitung fehlgeschlagen: {e}")
                raise
        raise RuntimeError("pypdf ist nicht installiert; PDF-Verarbeitung nicht möglich.")

    def extract_single_document(self, input_pdf: Path, start_page: int, end_page: int, output_pdf: Path) -> Path:
        """
        Zerschneidet das Eingabe-PDF von `start_page` bis `end_page` (1-basiert).
        """
        if HAS_PYPDF:
            try:
                reader = PdfReader(str(input_pdf))
                writer = PdfWriter()

                for p in range(start_page - 1, end_page):
                    if 0 <= p < len(reader.pages):
                        writer.add_page(reader.pages[p])

                output_pdf.parent.mkdir(parents=True, exist_ok=True)
                with open(output_pdf, "wb") as f:
                    writer.write(f)
                return output_pdf
            except Exception as exc:
                logger.exception(f"[PDFEngine ERROR] PDF-Splitting fehlgeschlagen: {exc}")
                raise
        raise RuntimeError("pypdf ist nicht installiert; PDF-Splitting nicht möglich.")


# Globale Instanz
pdf_engine = PDFEngine()
