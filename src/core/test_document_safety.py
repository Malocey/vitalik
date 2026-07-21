"""Schnelle Regressionstests für Beleg-Sicherheits- und Performancepfade."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.local_llm_client import LocalLLMClient
from src.core.validation_shield import ValidationShield
from src.parser.analyzer import DocumentAnalyzer
from src.parser.pdf_engine import pdf_engine


def test_boundaries_and_presegmented_analysis() -> None:
    pages = [
        {"page_num": 1, "full_text": "Rechnung A mit Rechnungsnummer RA-1 Seite 1 von 2"},
        {"page_num": 2, "full_text": "Fortgesetzte Rechnungspositionen Seite 2 von 2"},
        {"page_num": 3, "full_text": "Rechnung B mit Rechnungsnummer RB-2 Seite 1 von 1"},
        {"page_num": 4, "full_text": "Einzelbeleg mit ausreichend lesbarem Dokumentenkopf"},
    ]
    boundaries = DocumentAnalyzer().detect_boundaries(pages)
    assert [(item["start_page"], item["end_page"]) for item in boundaries] == [
        (1, 2), (3, 3), (4, 4)
    ]


def test_no_synthetic_llm_fallback() -> None:
    client = LocalLLMClient(
        provider="lm_studio", endpoints=["http://offline.invalid/v1"],
        request_timeout=0.01,
    )
    with patch(
        "src.core.local_llm_client.requests.post",
        side_effect=ConnectionError("offline"),
    ):
        try:
            client.generate_completion("Beleg", json_mode=True)
        except RuntimeError:
            return
    raise AssertionError("Ein Offline-LLM darf keine synthetischen Belegdaten liefern.")


def test_split_failure_does_not_copy_original() -> None:
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "invalid.pdf"
        target = Path(directory) / "part.pdf"
        source.write_bytes(b"kein PDF")
        try:
            pdf_engine.extract_single_document(source, 1, 1, target)
        except Exception:
            pass
        else:
            raise AssertionError("Ungültiges PDF hätte hart fehlschlagen müssen.")
        assert not target.exists()


def test_weak_ocr_blocks_booking() -> None:
    passed, _, doc = ValidationShield().validate_document({
        "belegtyp": "Rechnung", "ocr_status": "OCR_WEAK",
        "ocr_quality_score": 0.42, "confidence_score": 1.0,
        "netto": 100.0, "steuer": 19.0, "brutto": 119.0,
    })
    assert not passed
    assert doc["validation_status"] == "MANUAL_REVIEW_NEEDED"


if __name__ == "__main__":
    test_boundaries_and_presegmented_analysis()
    test_no_synthetic_llm_fallback()
    test_split_failure_does_not_copy_original()
    test_weak_ocr_blocks_booking()
    print("Dokument-Sicherheitstests erfolgreich")
