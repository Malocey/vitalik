"""Gemeinsame Regressionstests der drei deterministischen Jules-Engines."""

from src.parser.analyzer import DocumentAnalyzer
from src.parser.amount_parser import parse


def test_boundary_v2_is_used_by_analyzer() -> None:
    pages = [
        {"page_num": 1, "full_text": "Rechnung Nr. A Seite 1 von 2 mit Gesamtbetrag 119,00 EUR"},
        {"page_num": 2, "full_text": "Fortsetzung Seite 2 von 2 weitere Rechnungspositionen"},
        {"page_num": 3, "full_text": "Rechnung Nr. B Seite 1 von 1 Gesamtbetrag 59,50 EUR"},
    ]
    boundaries = DocumentAnalyzer().detect_boundaries(pages)
    assert [(item["start_page"], item["end_page"]) for item in boundaries] == [(1, 2), (3, 3)]
    assert all("boundary_confidence" in item for item in boundaries)


def test_deterministic_evidence_overrides_conflicting_llm_amounts() -> None:
    amount_result = parse(
        "Netto 100,00 EUR\nUmsatzsteuer 19 % 19,00 EUR\nGesamtbetrag 119,00 EUR"
    )
    type_result = {
        "document_type": "Rechnung", "confidence": 1.0,
        "status": "CLASSIFIED", "automatic_booking_allowed": True,
    }
    doc = {
        "belegtyp": "Sonstiges", "netto": 999.0, "steuer": 0.0,
        "brutto": 999.0, "confidence_score": 0.99,
    }
    DocumentAnalyzer._apply_deterministic_evidence(doc, type_result, amount_result)
    assert doc["belegtyp"] == "Rechnung"
    assert (doc["netto"], doc["steuer"], doc["brutto"]) == (100.0, 19.0, 119.0)
    assert doc["amount_match_source"] == "deterministic_amount_parser"


def test_ambiguous_amounts_never_override_existing_values() -> None:
    doc = {"netto": 10.0, "steuer": 1.9, "brutto": 11.9, "belegtyp": "Rechnung"}
    DocumentAnalyzer._apply_deterministic_evidence(
        doc,
        {"document_type": "Rechnung", "confidence": 0.7, "status": "AMBIGUOUS"},
        {
            "math_valid": True, "confidence": 0.99,
            "conflicts": ["Multiple competing amounts"],
            "net": {"value": 100.0}, "tax": {"value": 19.0},
            "gross": {"value": 119.0}, "tax_breakdown": [],
        },
    )
    assert (doc["netto"], doc["steuer"], doc["brutto"]) == (10.0, 1.9, 11.9)
