import pytest
from src.parser.boundary_detector_v2 import BoundaryDetectorV2, compare_boundaries

def test_three_single_page_invoices():
    detector = BoundaryDetectorV2()
    pages = [
        {"page_num": 1, "full_text": "Rechnung\nRechnungsnummer: 1001\nSeite 1 von 1\nGesamtbetrag: 100.00"},
        {"page_num": 2, "full_text": "Rechnung\nRechnungsnummer: 1002\nSeite 1 von 1\nGesamtbetrag: 200.00"},
        {"page_num": 3, "full_text": "Rechnung\nRechnungsnummer: 1003\nSeite 1 von 1\nGesamtbetrag: 300.00"}
    ]
    result = detector.detect(pages)
    assert len(result["documents"]) == 3
    assert result["documents"][0]["start_page"] == 1
    assert result["documents"][0]["end_page"] == 1
    assert result["documents"][1]["start_page"] == 2
    assert result["documents"][1]["end_page"] == 2
    assert result["documents"][2]["start_page"] == 3
    assert result["documents"][2]["end_page"] == 3

def test_invoice_with_three_pages():
    detector = BoundaryDetectorV2()
    pages = [
        {"page_num": 1, "full_text": "Rechnung\nRechnungsnummer: R-123\nSeite 1 von 3"},
        {"page_num": 2, "full_text": "Rechnungsnummer: R-123\nSeite 2 von 3\nÜbertrag"},
        {"page_num": 3, "full_text": "Rechnungsnummer: R-123\nSeite 3 von 3\nGesamtbetrag: 500.00"}
    ]
    result = detector.detect(pages)
    assert len(result["documents"]) == 1
    assert result["documents"][0]["start_page"] == 1
    assert result["documents"][0]["end_page"] == 3
    assert len(result["transitions"]) == 2
    assert result["transitions"][0]["is_boundary"] is False
    assert result["transitions"][1]["is_boundary"] is False

def test_two_multipage_invoices():
    detector = BoundaryDetectorV2()
    pages = [
        {"page_num": 1, "full_text": "Rechnung\nRechnungsnummer: A1\nSeite 1 von 2"},
        {"page_num": 2, "full_text": "Rechnungsnummer: A1\nSeite 2 von 2\nGesamtbetrag: 100.00"},
        {"page_num": 3, "full_text": "Rechnung\nRechnungsnummer: B2\nSeite 1 von 2"},
        {"page_num": 4, "full_text": "Rechnungsnummer: B2\nSeite 2 von 2\nGesamtbetrag: 200.00"}
    ]
    result = detector.detect(pages)
    assert len(result["documents"]) == 2
    assert result["documents"][0]["start_page"] == 1
    assert result["documents"][0]["end_page"] == 2
    assert result["documents"][1]["start_page"] == 3
    assert result["documents"][1]["end_page"] == 4

    # Check transitions
    assert result["transitions"][0]["is_boundary"] is False # 1->2
    assert result["transitions"][1]["is_boundary"] is True  # 2->3
    assert result["transitions"][2]["is_boundary"] is False # 3->4

def test_account_statement_10_pages():
    detector = BoundaryDetectorV2()
    pages = []
    for i in range(1, 11):
        pages.append({
            "page_num": i,
            "full_text": f"Kontoauszug\nKundennummer: K-999\nSeite {i} von 10" + ("\nFortsetzung" if i > 1 else "")
        })
    result = detector.detect(pages)
    assert len(result["documents"]) == 1
    assert result["documents"][0]["start_page"] == 1
    assert result["documents"][0]["end_page"] == 10
    assert len(result["transitions"]) == 9
    assert all(not t["is_boundary"] for t in result["transitions"])

def test_blank_page_between_documents():
    detector = BoundaryDetectorV2()
    pages = [
        {"page_num": 1, "full_text": "Rechnung 1\nRechnungsnummer: X1\nSeite 1 von 1"},
        {"page_num": 2, "full_text": "   "}, # Blank
        {"page_num": 3, "full_text": "Rechnung 2\nRechnungsnummer: X2\nSeite 1 von 1"}
    ]
    result = detector.detect(pages)
    assert len(result["documents"]) == 2
    assert len(result["unassigned_pages"]) == 1
    assert result["unassigned_pages"][0]["page_num"] == 2
    assert result["unassigned_pages"][0]["classification"] == "SEPARATOR_PAGE"

def test_almost_empty_backside():
    detector = BoundaryDetectorV2()
    pages = [
        {"page_num": 1, "full_text": "Rechnung 1\nRechnungsnummer: X1\nSeite 1 von 1\nGesamtbetrag: 100"},
        {"page_num": 2, "full_text": "AGB\nbla"}, # Not enough words
    ]
    result = detector.detect(pages)
    assert len(result["documents"]) == 1
    assert result["documents"][0]["start_page"] == 1
    assert result["documents"][0]["end_page"] == 1
    assert len(result["unassigned_pages"]) == 1
    assert result["unassigned_pages"][0]["page_num"] == 2
    assert result["unassigned_pages"][0]["classification"] == "BLANK_BACKSIDE"

def test_false_word_rechnung_on_continuation():
    detector = BoundaryDetectorV2()
    pages = [
        {"page_num": 1, "full_text": "Rechnung\nRechnungs-Nr: 555\nSeite 1 von 2"},
        {"page_num": 2, "full_text": "Rechnungs-Nr: 555\nSeite 2 von 2\nWir danken für diese Rechnung."}
    ]
    result = detector.detect(pages)
    assert len(result["documents"]) == 1

def test_same_supplier_consecutive_invoices():
    detector = BoundaryDetectorV2()
    # Different invoice numbers but same format
    pages = [
        {"page_num": 1, "full_text": "Lieferant GmbH\nRechnungs-Nr: 100\nDatum: 01.01.2023\nGesamtbetrag: 50.00"},
        {"page_num": 2, "full_text": "Lieferant GmbH\nRechnungs-Nr: 101\nDatum: 02.01.2023\nGesamtbetrag: 60.00"}
    ]
    result = detector.detect(pages)
    assert len(result["documents"]) == 2
    assert result["documents"][0]["end_page"] == 1
    assert result["documents"][1]["start_page"] == 2

def test_missing_ocr_page_insufficient_text():
    detector = BoundaryDetectorV2()
    pages = [
        {"page_num": 1, "full_text": "Rechnung\nRechnungsnummer: 1001\nSeite 1 von 1\nGesamtbetrag: 100.00"},
        {"page_num": 2, "full_text": "a"}, # Insufficient text, will be BLANK_BACKSIDE because follows content
        {"page_num": 3, "full_text": "Rechnung\nRechnungsnummer: 1002\nSeite 1 von 1\nGesamtbetrag: 200.00"}
    ]
    result = detector.detect(pages)
    assert len(result["documents"]) == 2
    assert len(result["unassigned_pages"]) == 1
    assert result["unassigned_pages"][0]["page_num"] == 2

def test_missing_page_numbers_warning():
    detector = BoundaryDetectorV2()
    pages = [
        {"page_num": 1, "full_text": "Rechnung\nRechnungsnummer: 1001\nSeite 1 von 3"},
        {"page_num": 3, "full_text": "Rechnungsnummer: 1001\nSeite 3 von 3\nGesamtbetrag: 100.00"}
    ]
    result = detector.detect(pages)
    assert len(result["documents"]) == 1
    assert "MISSING_PAGE_NUMBERS" in result["documents"][0]["warnings"]

def test_duplicate_page_numbers_raises_error():
    detector = BoundaryDetectorV2()
    pages = [
        {"page_num": 1, "full_text": "Rechnung A"},
        {"page_num": 1, "full_text": "Rechnung B"}
    ]
    with pytest.raises(ValueError, match="Duplicate page number found: 1"):
        detector.detect(pages)

def test_no_pages():
    detector = BoundaryDetectorV2()
    result = detector.detect([])
    assert len(result["documents"]) == 0
    assert len(result["unassigned_pages"]) == 0

def test_only_one_page():
    detector = BoundaryDetectorV2()
    pages = [{"page_num": 1, "full_text": "Rechnung\nRechnungsnummer: 1001\nSeite 1 von 1\nGesamtbetrag: 100.00"}]
    result = detector.detect(pages)
    assert len(result["documents"]) == 1
    assert result["documents"][0]["start_page"] == 1
    assert result["documents"][0]["end_page"] == 1

def test_every_page_exactly_assigned():
    detector = BoundaryDetectorV2()
    pages = [
        {"page_num": 1, "full_text": "Rechnung\nRechnungsnummer: 1\nSeite 1 von 1"},
        {"page_num": 2, "full_text": "   "},
        {"page_num": 3, "full_text": "Rechnung\nRechnungsnummer: 2\nSeite 1 von 1"}
    ]
    result = detector.detect(pages)
    # Check that invariant didn't raise RuntimeError
    # And manually verify
    unassigned = {p["page_num"] for p in result["unassigned_pages"]}
    doc_pages = set()
    for d in result["documents"]:
        doc_pages.add(d["start_page"])
        doc_pages.add(d["end_page"]) # they are the same here

    assert 1 in doc_pages
    assert 2 in unassigned
    assert 3 in doc_pages
    assert len(unassigned) + len(set(doc_pages)) == 3

def test_compare_boundaries():
    expected = {
        "documents": [
            {"start_page": 1, "end_page": 2},
            {"start_page": 3, "end_page": 3}
        ]
    }
    predicted = {
        "documents": [
            {"start_page": 1, "end_page": 2},
            {"start_page": 3, "end_page": 4} # predicted wrong end page
        ]
    }
    metrics = compare_boundaries(expected, predicted)
    assert metrics["exact_precision"] == 0.5
    assert metrics["exact_recall"] == 0.5
    assert metrics["start_page_accuracy"] == 1.0
    assert metrics["end_page_accuracy"] == 0.5
    # page assignment:
    # expected map: {1: (1,2), 2: (1,2), 3: (3,3)} - 3 pages
    # predicted map: {1: (1,2), 2: (1,2), 3: (3,4), 4: (3,4)}
    # correct pages: 1 and 2. 3 is wrong because predicted bounds are (3,4) instead of (3,3).
    # so 2 / 3 = 0.666...
    assert pytest.approx(metrics["page_assignment_accuracy"], 0.01) == 0.666

def test_contradicting_page_numbers():
    detector = BoundaryDetectorV2()
    pages = [
        {"page_num": 1, "full_text": "Rechnung\nSeite 1 von 3\nRechnungsnummer: 123"},
        {"page_num": 2, "full_text": "Seite 4 von 3\nRechnungsnummer: 123\nÜbertrag"}, # contradiction, but same invoice num
    ]
    result = detector.detect(pages)
    # The contradiction in page numbers won't trigger page 1 of N, but it will trigger X of N.
    # Same invoice number will be a strong continuation signal.
    # It should not split arbitrarily.
    assert len(result["documents"]) == 1
    assert result["documents"][0]["start_page"] == 1
    assert result["documents"][0]["end_page"] == 2
