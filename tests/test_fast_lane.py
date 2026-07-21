import json
import pytest
from pathlib import Path
from src.core.fast_lane import FastLaneRouter

def get_base_valid_doc():
    fixture_path = Path("tests/fixtures/synthetic_invoice_001.expected.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        expected = json.load(f)

    # Map the expected flat fixture JSON back to the input dictionary format
    # expected by the router
    return {
        "input_valid": True,
        "context_character_count": 2400,
        "pages": [{"text": "dummy"}] * expected.get("pages", 1),
        "ocr_quality_score": 0.92,
        "boundary_confidence": 0.96,
        "duplicate_warning": False,
        "document_type_result": {
            "document_type": expected.get("document_type"),
            "confidence": 0.98,
            "status": "CLASSIFIED"
        },
        "amount_result": {
            "net": {"value": expected.get("net"), "currency": expected.get("currency")},
            "tax": {"value": expected.get("tax"), "currency": expected.get("currency")},
            "gross": {"value": expected.get("gross"), "currency": expected.get("currency")},
            "math_valid": True,
            "math_difference": 0.0,
            "confidence": 0.97,
            "conflicts": []
        },
        "supplier_result": {
            "value": expected.get("supplier"),
            "found": True,
            "confidence": 0.96,
            "conflicts": []
        },
        "invoice_number_result": {
            "value": expected.get("invoice_number"),
            "found": True,
            "confidence": 0.95,
            "conflicts": []
        }
    }

def test_fast_lane_routing():
    router = FastLaneRouter()
    doc = get_base_valid_doc()
    res = router.route(doc)

    assert res["route"] == "FAST_LANE"
    assert res["saved_llm_call"] is True
    assert res["llm_required"] is False
    # confidence min of: ocr(0.92), boundary(0.96), doctype(0.98), sup(0.96), inv(0.95), amt(0.97) -> 0.92
    assert res["confidence"] == 0.92

def test_targeted_llm_missing_invoice():
    router = FastLaneRouter()
    doc = get_base_valid_doc()
    # Missing invoice number
    doc["invoice_number_result"]["found"] = False

    res = router.route(doc)
    assert res["route"] == "TARGETED_LLM"
    assert "invoice_number" in res["llm_prompt_fields"]
    assert res["llm_required"] is True
    assert res["saved_llm_call"] is False

def test_manual_review_low_ocr():
    router = FastLaneRouter()
    doc = get_base_valid_doc()
    doc["ocr_quality_score"] = 0.65

    res = router.route(doc)
    assert res["route"] == "MANUAL_REVIEW"
    assert "low_ocr_score" in res["blocking_reasons"]
    assert res["confidence"] == 1.0

def test_manual_review_protected_document():
    router = FastLaneRouter()
    doc = get_base_valid_doc()
    doc["document_type_result"]["document_type"] = "Kontoauszug"

    res = router.route(doc)
    assert res["route"] == "MANUAL_REVIEW"
    assert "protected_document_type" in res["blocking_reasons"]

def test_manual_review_currency_conflict():
    router = FastLaneRouter()
    doc = get_base_valid_doc()
    doc["amount_result"]["conflicts"] = [{"type": "currency", "msg": "conflict"}]

    res = router.route(doc)
    assert res["route"] == "MANUAL_REVIEW"
    assert "currency_conflict" in res["blocking_reasons"]
    assert "amount_conflict" in res["blocking_reasons"]

def test_rejected_empty_page():
    router = FastLaneRouter()
    doc = get_base_valid_doc()
    doc["pages"] = []
    doc["context_character_count"] = 0

    res = router.route(doc)
    assert res["route"] == "REJECTED"
    assert "no_pages" in res["blocking_reasons"]

def test_rejected_input_invalid():
    router = FastLaneRouter()
    res = router.route({"input_valid": False})
    assert res["route"] == "REJECTED"

def test_full_llm_unknown_layout():
    router = FastLaneRouter()
    doc = get_base_valid_doc()
    doc["supplier_result"] = None
    doc["invoice_number_result"] = {"value": "UNKNOWN"}
    doc["amount_result"]["math_valid"] = False

    res = router.route(doc)
    assert res["route"] == "FULL_LLM"
    assert len(res["missing_fields"]) == 3

def test_none_dictionary():
    router = FastLaneRouter()
    doc = get_base_valid_doc()
    doc["supplier_result"] = None
    res = router.route(doc)
    # 1 missing field -> TARGETED_LLM
    assert res["route"] == "TARGETED_LLM"
    assert "supplier" in res["missing_fields"]

def test_unknown_and_regex_values():
    router = FastLaneRouter()
    doc = get_base_valid_doc()
    doc["supplier_result"]["value"] = "UNBEKANNT"
    doc["invoice_number_result"]["value"] = "REG-EXPR"
    res = router.route(doc)
    assert res["route"] == "TARGETED_LLM"
    assert "supplier" in res["missing_fields"]
    assert "invoice_number" in res["missing_fields"]

def test_ambiguous_doc_type():
    router = FastLaneRouter()
    doc = get_base_valid_doc()
    doc["document_type_result"]["status"] = "AMBIGUOUS"
    res = router.route(doc)
    assert res["route"] == "MANUAL_REVIEW"
    assert "ambiguous_document_type" in res["blocking_reasons"]

def test_math_difference_too_high():
    router = FastLaneRouter()
    doc = get_base_valid_doc()
    doc["amount_result"]["math_difference"] = 0.05
    res = router.route(doc)
    assert res["route"] == "TARGETED_LLM"
    assert "amount_details" in res["missing_fields"]

def test_credit_note_negative_amounts():
    router = FastLaneRouter()
    doc = get_base_valid_doc()
    doc["document_type_result"]["document_type"] = "Gutschrift"
    doc["amount_result"]["net"]["value"] = -100.0
    doc["amount_result"]["tax"]["value"] = -19.0
    doc["amount_result"]["gross"]["value"] = -119.0
    res = router.route(doc)
    assert res["route"] == "FAST_LANE"

def test_batch_all_routes():
    router = FastLaneRouter()

    doc_fast = get_base_valid_doc()
    doc_target = get_base_valid_doc()
    doc_target["supplier_result"]["found"] = False

    doc_full = get_base_valid_doc()
    doc_full["supplier_result"] = None
    doc_full["invoice_number_result"] = None
    doc_full["amount_result"] = None

    doc_manual = get_base_valid_doc()
    doc_manual["duplicate_warning"] = True

    doc_reject = {"input_valid": False}

    batch = [doc_fast, doc_target, doc_full, doc_manual, doc_reject]
    res = router.route_batch(batch)

    assert res["summary"]["total_documents"] == 5
    routes = res["summary"]["route_distribution"]
    assert routes["FAST_LANE"] == 1
    assert routes["TARGETED_LLM"] == 1
    assert routes["FULL_LLM"] == 1
    assert routes["MANUAL_REVIEW"] == 1
    assert routes["REJECTED"] == 1

    assert res["summary"]["fast_lane_share"] == 0.2
    assert res["summary"]["llm_required_count"] == 2
    assert res["summary"]["llm_calls_avoided"] == 1

def test_empty_batch_division_by_zero():
    router = FastLaneRouter()
    res = router.route_batch([])
    assert res["summary"]["total_documents"] == 0
    assert res["summary"]["fast_lane_share"] == 0.0
    assert res["summary"]["expected_llm_savings_rate"] == 0.0

def test_config_token_time_estimation():
    router = FastLaneRouter(
        chars_per_token=2,
        prompt_overhead_tokens=100,
        tokens_per_requested_field=50,
        tokens_per_second=10.0
    )
    doc = get_base_valid_doc()
    doc["supplier_result"]["found"] = False
    # ctx chars: 2400 -> tokens = 1200
    # overhead: 100
    # missing fields: 1 -> 50
    # Total tokens = 1200 + 100 + 50 = 1350
    # Time = 1350 / 10 = 135.0

    res = router.route(doc)
    assert res["route"] == "TARGETED_LLM"
    assert res["estimated_tokens"] == 1350
    assert res["estimated_time_seconds"] == 135.0
