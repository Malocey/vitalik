"""
Massen-Pipeline & Trenn-Skript für VG Delikatessen.
Verarbeitet PDF-Scans speichereffizient, führt den 3-Stufen Schutzschild aus
und protokolliert den Fortschritt in checkpoint.json für Unterbrechungsfreiheit bei 20.000 Seiten.
"""

import datetime
import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, List
from src.core.config import (
    CHECKPOINT_FILE, TESTDATA_DIR, LM_STUDIO_ENDPOINTS,
    LLM_MAX_IN_FLIGHT_PER_ENDPOINT,
)
from src.parser.pdf_engine import pdf_engine
from src.parser.analyzer import document_analyzer
from src.core.validation_shield import validation_shield
from src.core.rag_engine import rag_engine
from src.core.mocks import mock_drive, mock_telegram, mock_sevdesk
from src.drive.sorter import DriveSorter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Pipeline")


class ArchivePipeline:
    def __init__(self, checkpoint_file: Path = CHECKPOINT_FILE):
        self.checkpoint_file = checkpoint_file
        self.checkpoint = self._load_checkpoint()
        self.sorter = DriveSorter()

    def _load_checkpoint(self) -> Dict[str, Any]:
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"processed_files": [], "last_page": 0}

    def _save_checkpoint(self):
        with open(self.checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(self.checkpoint, f, ensure_ascii=False, indent=2)

    def process_pdf_archive(self, pdf_path: Path, source_action: str = "archive") -> List[Dict[str, Any]]:
        """
        Verarbeitet eine mehrseitige PDF-Archivdatei stapelweise und parallel.
        Speichert Ergebnisse inkrementell und verschiebt die Quelldatei nach Abschluss.
        """
        import datetime
        import threading
        import shutil
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        logger.info(f"[Pipeline] Starte Verarbeitung von {pdf_path.name}...")
        
        pages_info = pdf_engine.inspect_pdf(pdf_path)
        logger.info(f"[Pipeline] {len(pages_info)} Seiten in {pdf_path.name} analysiert.")

        # Grenzen der einzelnen Belege im Stapel erkennen
        boundaries = document_analyzer.detect_boundaries(pages_info)
        filtered_boundaries = []
        for boundary in boundaries:
            boundary_text = " ".join(
                page.get("full_text") or ""
                for page in pages_info
                if boundary["start_page"] <= page["page_num"] <= boundary["end_page"]
            )
            useful_characters = len("".join(character for character in boundary_text if character.isalnum()))
            if useful_characters < 80:
                logger.warning(
                    f"[Pipeline] Leere/zu kurze Trennseiten {boundary['start_page']}-{boundary['end_page']} "
                    f"übersprungen ({useful_characters} Nutzzeichen)."
                )
                continue
            filtered_boundaries.append(boundary)
        boundaries = filtered_boundaries
        total_docs = len(boundaries)
        logger.info(f"[Pipeline] Erkannte Belege im Stapel: {total_docs}")

        processed_results = []
        db_lock = threading.Lock()

        # Definition des Workers, der ein einzelnes Dokument analysiert und speichert
        def process_and_save_worker(bound_info):
            idx, bound = bound_info
            start = bound["start_page"]
            end = bound["end_page"]
            
            try:
                # 1. Temporär zerschneiden, um MD5-Hash zu berechnen
                temp_dir = Path("data/temp")
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_pdf_path = temp_dir / f"temp_split_{start}_{end}_{idx}.pdf"
                pdf_engine.extract_single_document(pdf_path, start, end, temp_pdf_path)
                
                md5_hash = pdf_engine.calculate_md5(temp_pdf_path)
                
                # Check MD5
                with db_lock:
                    is_md5_dup = self.sorter.check_md5_exists(md5_hash)
                
                if temp_pdf_path.exists():
                    temp_pdf_path.unlink()
                    
                if is_md5_dup:
                    existing_doc = rag_engine.find_beleg_by_md5(md5_hash)
                    if existing_doc:
                        # Die Seitenpositionen beziehen sich auf das aktuelle
                        # Sammel-PDF und müssen beim Resume erneut gesetzt werden.
                        existing_doc["start_seite"] = start
                        existing_doc["end_seite"] = end
                        logger.info(
                            f"[Pipeline] Bereits persistenter Teilbeleg {existing_doc['beleg_id']} "
                            f"wird ohne Neuanlage wiederverwendet."
                        )
                        res = {
                            "doc": existing_doc,
                            "passed": existing_doc.get("status") == "PASSED",
                            "reason": "Bereits vollständig persistent (MD5)",
                            "saved_path": existing_doc.get("beleg_link", ""),
                            "telegram_msg": "[System] Bereits persistenter Teilbeleg wiederverwendet.",
                        }
                        with db_lock:
                            processed_results.append(res)
                        return res
                    doc_data = {
                        "lieferant": "DUBLITTE_MD5",
                        "datum": datetime.datetime.now().strftime("%Y-%m-%d"),
                        "brutto": 0.0,
                        "netto": 0.0,
                        "steuer": 0.0,
                        "md5_hash": md5_hash,
                        "validation_status": "DUBLITTE_MD5",
                        "start_seite": start,
                        "end_seite": end
                    }
                    
                    # Thread-sicheres Speichern
                    with db_lock:
                        logger.warning(f"[Pipeline] MD5-Dublette erkannt für Beleg {idx}/{total_docs}: {md5_hash}. Überspringe Analyse.")
                        sort_result = self.sorter.sort_and_save_pdf(pdf_path, start, end, doc_data)
                        
                    res = {
                        "doc": doc_data,
                        "passed": False,
                        "reason": "MD5-Duplikat",
                        "saved_path": "DUBLITTEN_MD5_NO_SAVE",
                        "telegram_msg": "[System] MD5-Duplikat erkannt."
                    }
                    with db_lock:
                        processed_results.append(res)
                    return res

                # 3. Inhaltliche Analyse des Einzeldokuments (LLM Abfrage)
                doc_pages = [p for p in pages_info if start <= p["page_num"] <= end]
                doc_data = document_analyzer.analyze_document(doc_pages)
                doc_data["md5_hash"] = md5_hash

                # 4. Validierung
                passed, reason, enriched_doc = validation_shield.validate_document(doc_data)
                
                # 5. Thread-sichere Speicherung, sevDesk-Buchung und Telegram-Push
                with db_lock:
                    logger.info(f"[Pipeline] [Speicherung] Beleg {idx}/{total_docs} (Seiten {start}-{end}) wird sortiert...")
                    sort_result = self.sorter.sort_and_save_pdf(
                        input_pdf_path=pdf_path,
                        start_page=start,
                        end_page=end,
                        doc_data=enriched_doc
                    )
                    saved_path = sort_result["saved_path"]

                    # Buchung in sevDesk
                    if (
                        sort_result.get("passed") is True
                        and enriched_doc.get("validation_status") == "PASSED"
                        and enriched_doc.get("persistence_verified") is True
                    ):
                        mock_sevdesk.post_voucher(enriched_doc)

                    # Telegram Push
                    telegram_msg = mock_telegram.send_approval_request(enriched_doc)
                    
                    res = {
                        "doc": enriched_doc,
                        "passed": passed,
                        "reason": reason,
                        "saved_path": str(saved_path),
                        "telegram_msg": telegram_msg
                    }
                    processed_results.append(res)
                    return res

            except Exception as e:
                logger.error(f"[Pipeline] Fehler bei Beleg {idx}/{total_docs} (Seiten {start}-{end}): {e}")
                res = {
                    "doc": {"start_seite": start, "end_seite": end, "lieferant": "FEHLER"},
                    "passed": False,
                    "reason": f"Verarbeitungsfehler: {str(e)}",
                    "saved_path": "None",
                    "telegram_msg": "[System] Verarbeitungsfehler."
                }
                with db_lock:
                    processed_results.append(res)
                return res

        # Parallel verarbeiten (Gemma 4 entlasten: max 2 Worker)
        configured_capacity = max(
            1, len(LM_STUDIO_ENDPOINTS) * LLM_MAX_IN_FLIGHT_PER_ENDPOINT
        )
        max_llm_workers = min(configured_capacity, total_docs) if total_docs > 0 else 1
        logger.info(f"[Pipeline] Starte parallele KI-Extraktion und SOFORTIGES Speichern mit {max_llm_workers} Workern...")
        
        boundary_list = list(enumerate(boundaries, 1))
        with ThreadPoolExecutor(max_workers=max_llm_workers) as executor:
            futures = [executor.submit(process_and_save_worker, b) for b in boundary_list]
            for future in as_completed(futures):
                future.result()

        fully_persistent = (
            total_docs > 0
            and len(processed_results) == total_docs
            and all(
                result.get("doc", {}).get("persistence_verified") is True
                for result in processed_results
            )
        )
        if fully_persistent:
            self.checkpoint["processed_files"].append(pdf_path.name)
            self._save_checkpoint()
            try:
                if source_action == "done":
                    done_path = pdf_path.with_name(f"Done_{pdf_path.name}")
                    if done_path.exists():
                        raise FileExistsError(f"Done-Zieldatei existiert bereits: {done_path}")
                    pdf_path.rename(done_path)
                    logger.info(f"[Pipeline] Quelldatei erfolgreich markiert: {done_path}")
                elif source_action == "archive":
                    archive_dir = pdf_path.parent / "archived"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    archived_path = archive_dir / pdf_path.name
                    shutil.move(str(pdf_path), str(archived_path))
                    logger.info(f"[Pipeline] Quelldatei erfolgreich abgeheftet unter: {archived_path}")
                elif source_action != "keep":
                    raise ValueError(f"Unbekannte source_action: {source_action}")
            except Exception as ae:
                logger.error(f"[Pipeline] Fehler beim Markieren der Quelldatei: {ae}")
        else:
            logger.error(
                "[Pipeline] Quelldatei bleibt unverändert: Nicht alle Belege wurden vollständig persistent gespeichert."
            )

        logger.info(f"[Pipeline] Verarbeitung von {pdf_path.name} abgeschlossen.")
        return processed_results


# Globale Instanz
archive_pipeline = ArchivePipeline()
