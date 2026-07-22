import pytest
import json
import tempfile
from pathlib import Path
from src.core.benchmark_rag_retrieval import calculate_metrics, check_thresholds, GroundTruthItem, run_benchmark
from src.core.rag_engine import rag_engine as global_rag_engine

def test_calculate_metrics():
    gt = GroundTruthItem(
        query_id="q1",
        query="test",
        query_type="entity",
        expected_entity_id="wiki_1",
        expected_doc_ids=["doc_1", "doc_2"],
        allowed_categories=["beleg"],
        expected_sources=["wiki"]
    )

    results = [
        {
            "ground_truth": gt,
            "retrieved": [
                {"doc_id": "wiki_1", "source": "wiki", "category": "wiki_lieferant"},
                {"doc_id": "doc_1", "source": "fts5", "category": "beleg"},
                {"doc_id": "doc_3", "source": "fts5", "category": "beleg"}
            ]
        }
    ]

    thresholds = {
        "hit@1": 1.0,
        "hit@3": 1.0,
        "hit@5": 1.0,
        "mrr": 1.0,
        "duplicate_rate": 0.0,
        "false_entity_rate": 0.05,
        "supplier_hub_first_rate": 1.0,
    }

    metrics = calculate_metrics(results, thresholds)

    assert metrics["overall"]["hit@1"] == 1.0
    assert metrics["overall"]["exact_supplier_hub_first_rate"] == 1.0
    assert metrics["overall"]["duplicate_query_rate@5"] == 0.0
    assert metrics["overall"]["false_entity_rate"] == 0.0

def test_check_thresholds_pass():
    metrics = {
        "overall": {
            "hit@1": 0.9,
            "hit@3": 0.95,
            "hit@5": 0.98,
            "mrr": 0.92,
            "duplicate_query_rate@5": 0.0,
            "false_entity_rate": 0.02,
            "exact_supplier_hub_first_rate": 1.0
        }
    }
    thresholds = {
        "hit@1": 0.8,
        "hit@3": 0.9,
        "hit@5": 0.95,
        "mrr": 0.85,
        "duplicate_rate": 0.0,
        "false_entity_rate": 0.05,
        "supplier_hub_first_rate": 1.0,
    }
    assert check_thresholds(metrics, thresholds) == True

def test_check_thresholds_fail():
    metrics = {
        "overall": {
            "hit@1": 0.7,
            "hit@3": 0.95,
            "hit@5": 0.98,
            "mrr": 0.92,
            "duplicate_query_rate@5": 0.0,
            "false_entity_rate": 0.02,
            "exact_supplier_hub_first_rate": 1.0
        }
    }
    thresholds = {
        "hit@1": 0.8,
        "hit@3": 0.9,
        "hit@5": 0.95,
        "mrr": 0.85,
        "duplicate_rate": 0.0,
        "false_entity_rate": 0.05,
        "supplier_hub_first_rate": 1.0,
    }
    assert check_thresholds(metrics, thresholds) == False

def test_structural_mode_invalid_schema():
    with tempfile.TemporaryDirectory() as temp_dir:
        gt_path = Path(temp_dir) / "gt.jsonl"
        with open(gt_path, "w") as f:
            f.write(json.dumps({"query_id": "1", "query": "test", "query_type": "invalid_type", "expected_entity_id": None}) + "\n")

        assert not run_benchmark("structural", gt_path, Path(temp_dir) / "out", {})

def test_fixture_mode_isolation():
    initial_db_path = global_rag_engine.db_path

    with tempfile.TemporaryDirectory() as temp_dir:
        out_dir = Path(temp_dir) / "out"
        # Run fixture twice to ensure no state pollution
        assert run_benchmark("fixture", Path("tests/fixtures/rag_ground_truth.jsonl"), out_dir, {
            "hit@1": 0.0, "hit@3": 0.0, "hit@5": 0.0, "mrr": 0.0, "duplicate_rate": 1.0, "false_entity_rate": 1.0, "supplier_hub_first_rate": 0.0
        })
        assert run_benchmark("fixture", Path("tests/fixtures/rag_ground_truth.jsonl"), out_dir, {
            "hit@1": 0.0, "hit@3": 0.0, "hit@5": 0.0, "mrr": 0.0, "duplicate_rate": 1.0, "false_entity_rate": 1.0, "supplier_hub_first_rate": 0.0
        })

    assert global_rag_engine.db_path == initial_db_path

def test_fixture_ocr_fallback():
    # Verify that the ocr_only_01 query correctly utilizes the fallback
    with tempfile.TemporaryDirectory() as temp_dir:
        out_dir = Path(temp_dir) / "out"
        run_benchmark("fixture", Path("tests/fixtures/rag_ground_truth.jsonl"), out_dir, {
            "hit@1": 0.0, "hit@3": 0.0, "hit@5": 0.0, "mrr": 0.0, "duplicate_rate": 1.0, "false_entity_rate": 1.0, "supplier_hub_first_rate": 0.0
        })

        with open(out_dir / "benchmark_rag_results.json", "r") as f:
            res = json.load(f)

        assert res["metrics"]["source_hit_rates"]["ocr_fallback_usage"] > 0
        assert res["metrics"]["source_hit_rates"]["correct_only_by_ocr"] > 0
