import logging
import time
import re
from pathlib import Path
from typing import Callable, Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from src.parser.pdf_engine import pdf_engine
from src.parser.analyzer import document_analyzer
from src.core.rag_engine import rag_engine
from src.parser.amount_parser import parse as parse_amounts
from src.parser.document_type_classifier import DocumentTypeClassifier

logger = logging.getLogger("BenchmarkEvaluator")

@dataclass
class BenchmarkResult:
    filename: str
    runtime_inspect: float
    runtime_analysis: float
    boundaries: List[Dict[str, int]]
    extracted_docs: List[Dict[str, Any]]
    cache_hits_before: int
    cache_misses_before: int
    error: Optional[str] = None
    llm_worker: str = "not_available"


class BenchmarkEvaluator:
    def __init__(
        self,
        mode: str,
        fixture_extractor: Optional[Callable[[List[Dict[str, Any]]], Dict[str, Any]]] = None,
    ):
        self.mode = mode
        self.pdf_engine = pdf_engine
        self.document_analyzer = document_analyzer
        self.rag_engine = rag_engine
        self.type_classifier = DocumentTypeClassifier()
        self.fixture_extractor = fixture_extractor

    def check_cache(self, pdf_path: Path) -> Tuple[int, int]:
        """Checks cache hits and misses before run."""
        try:
            if not hasattr(self.pdf_engine, "calculate_md5"):
                return 0, 0

            md5 = self.pdf_engine.calculate_md5(pdf_path)
            cache_dir = Path("data/ocr_cache") / md5

            hits = 0
            if cache_dir.exists():
                hits = len(list(cache_dir.glob("*.json")))

            return hits, 0
        except Exception as e:
            logger.warning(f"Failed to check cache: {e}")
            return 0, 0

    def evaluate_pdf(self, pdf_path: Path) -> BenchmarkResult:
        logger.info(f"Evaluierung von {pdf_path.name}")

        cache_hits, _ = self.check_cache(pdf_path)

        start_time = time.time()
        try:
            pages_info = self.pdf_engine.inspect_pdf(pdf_path)
        except Exception as e:
            logger.error(f"Error inspecting {pdf_path.name}: {e}")
            return BenchmarkResult(
                filename=pdf_path.name,
                runtime_inspect=time.time() - start_time,
                runtime_analysis=0.0,
                boundaries=[],
                extracted_docs=[],
                cache_hits_before=cache_hits,
                cache_misses_before=0,
                error="OCR_FAILED"
            )

        runtime_inspect = time.time() - start_time

        if not pages_info:
            return BenchmarkResult(
                filename=pdf_path.name,
                runtime_inspect=runtime_inspect,
                runtime_analysis=0.0,
                boundaries=[],
                extracted_docs=[],
                cache_hits_before=cache_hits,
                cache_misses_before=0,
                error="NO_TEXT"
            )

        cache_misses = len(pages_info) - cache_hits
        if cache_misses < 0:
            cache_misses = 0

        # Boundary detection
        try:
            boundaries = self.document_analyzer.detect_boundaries(pages_info)
        except Exception as e:
            logger.error(f"Error detecting boundaries for {pdf_path.name}: {e}")
            return BenchmarkResult(
                filename=pdf_path.name,
                runtime_inspect=runtime_inspect,
                runtime_analysis=0.0,
                boundaries=[],
                extracted_docs=[],
                cache_hits_before=cache_hits,
                cache_misses_before=cache_misses,
                error="ANALYSIS_ERROR"
            )

        extracted_docs = []
        llm_worker = "not_available"
        runtime_analysis = 0.0

        for bound in boundaries:
            start = bound["start_page"]
            end = bound["end_page"]
            doc_pages = [p for p in pages_info if start <= p["page_num"] <= end]

            combined_text = ""
            total_ocr_chars = 0
            ocr_scores = []
            for p in doc_pages:
                text = p.get('full_text') or ""
                combined_text += f"\n--- SEITE {p['page_num']} ---\n" + text

                # Count alphanumeric chars for OCR character count
                total_ocr_chars += len("".join(character for character in text if character.isalnum()))

                # Collect OCR scores if not text layer
                if p.get("ocr_status") != "TEXT_LAYER" and p.get("ocr_confidence") is not None:
                    ocr_scores.append(float(p.get("ocr_confidence")))

            ocr_quality_score = min(ocr_scores) if ocr_scores else 1.0

            doc_data = {
                "start_seite": start,
                "end_seite": end,
                "raw_text": combined_text,
                "ocr_character_count": total_ocr_chars,
                "ocr_quality_score": ocr_quality_score,
                "llm_calls": 0 if self.mode == "structural" else None,
                "error": None
            }

            analysis_start = time.time()
            if self.mode == "structural":
                protected_type = self.document_analyzer.detect_high_priority_document_type(combined_text)
                if protected_type:
                    doc_data.update(protected_type)
                else:
                    regex_data = self.document_analyzer.try_regex_extraction(combined_text)
                    if regex_data:
                        doc_data.update(regex_data)
                type_result = self.type_classifier.classify(
                    combined_text, pages=len(doc_pages), ocr_quality=ocr_quality_score
                )
                amount_result = parse_amounts(doc_pages)
                doc_data["document_type_evidence"] = type_result
                doc_data["amount_evidence"] = amount_result
                if type_result.get("status") == "CLASSIFIED":
                    doc_data["belegtyp"] = type_result.get("document_type")
                if amount_result.get("math_valid") and not amount_result.get("conflicts"):
                    for source, target in (("net", "netto"), ("tax", "steuer"), ("gross", "brutto")):
                        candidate = amount_result.get(source)
                        if candidate:
                            doc_data[target] = candidate.get("value")
                required = ("lieferant", "belegtyp", "netto", "steuer", "brutto")
                if any(doc_data.get(field) in (None, "", "UNKNOWN") for field in required):
                    doc_data["error"] = "STRUCTURAL_INCOMPLETE"

            elif self.mode == "live":
                try:
                    res = self.document_analyzer.analyze_document(doc_pages)
                    doc_data.update(res)
                    # Try extracting worker ID if available in future, but currently:
                    llm_worker = "not_available"
                except Exception as e:
                    err_str = str(e).lower()
                    if "timeout" in err_str or "connection" in err_str or "worker" in err_str:
                        doc_data["error"] = "LLM_UNAVAILABLE"
                    else:
                        doc_data["error"] = "ANALYSIS_ERROR"
            elif self.mode == "fixture":
                if self.fixture_extractor is None:
                    doc_data["error"] = "FIXTURE_NOT_CONFIGURED"
                else:
                    doc_data.update(self.fixture_extractor(doc_pages))
                    doc_data["synthetic_fixture"] = True
                    doc_data["llm_calls"] = 0

            analysis_time = time.time() - analysis_start
            runtime_analysis += analysis_time

            # Mathematical consistency check
            netto = doc_data.get("netto")
            steuer = doc_data.get("steuer")
            brutto = doc_data.get("brutto")
            math_consistent = False
            if netto is not None and steuer is not None and brutto is not None:
                if abs((float(netto) + float(steuer)) - float(brutto)) <= 0.02:
                    math_consistent = True
            doc_data["math_consistent"] = math_consistent

            # RAG Search (Read-only)
            try:
                search_query = self.document_analyzer._build_rag_query(combined_text)
                rag_start = time.time()
                rag_hits = self.rag_engine.search(search_query, top_k=5)
                rag_time = time.time() - rag_start

                doc_data["rag_hits_count"] = len(rag_hits)
                doc_data["rag_search_time"] = rag_time
                doc_data["rag_scores"] = [h.get("score") for h in rag_hits]
                doc_data["rag_doc_ids"] = [h.get("doc_id") for h in rag_hits]
                doc_data["rag_categories"] = [h.get("kategorie") or h.get("category") for h in rag_hits]
                doc_data["rag_sources"] = [h.get("quelle") or h.get("source") for h in rag_hits]

            except Exception as e:
                logger.warning(f"RAG search failed for {pdf_path.name}: {e}")
                doc_data["rag_hits_count"] = 0
                doc_data["rag_search_time"] = 0.0
                doc_data["rag_scores"] = []
                doc_data["rag_doc_ids"] = []
                doc_data["rag_categories"] = []
                doc_data["rag_sources"] = []

            extracted_docs.append(doc_data)

        return BenchmarkResult(
            filename=pdf_path.name,
            runtime_inspect=runtime_inspect,
            runtime_analysis=runtime_analysis,
            boundaries=boundaries,
            extracted_docs=extracted_docs,
            cache_hits_before=cache_hits,
            cache_misses_before=cache_misses,
            llm_worker=llm_worker
        )
