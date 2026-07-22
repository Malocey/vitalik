import pytest
from pathlib import Path
from src.core.benchmark_rag_retrieval import calculate_metrics, check_thresholds, GroundTruthItem

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
