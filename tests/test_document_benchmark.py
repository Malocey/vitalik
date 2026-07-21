import pytest
import os
import csv
import json
import tempfile
import sys
from pathlib import Path
from src.core.benchmark_document_pipeline import load_expected_csv, calculate_metrics
from src.core.benchmark_evaluator import BenchmarkResult, BenchmarkEvaluator

def test_load_expected_csv():
    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", delete=False) as f:
        f.write("dateiname;startseite;endseite;dokumenttyp;lieferant;datum;rechnungsnummer;netto;steuer;brutto\n")
        f.write("test.pdf;1;2;Rechnung;Test GmbH;2024-01-01;RE-123;10,00;1.9;11.90\n")
        tmp_path = f.name

    try:
        data = load_expected_csv(Path(tmp_path))
        assert len(data) == 1
        assert data[0]["dateiname"] == "test.pdf"
        assert data[0]["startseite"] == 1
        assert data[0]["endseite"] == 2
        assert data[0]["netto"] == 10.0
        assert data[0]["steuer"] == 1.9
        assert data[0]["brutto"] == 11.9
    finally:
        os.unlink(tmp_path)


def test_metrics_calculation():
    expected = [
        {
            "dateiname": "test.pdf",
            "startseite": 1,
            "endseite": 2,
            "netto": 100.0,
            "steuer": 19.0,
            "brutto": 119.0
        }
    ]

    results = [
        BenchmarkResult(
            filename="test.pdf",
            runtime_inspect=1.0,
            runtime_analysis=0.5,
            boundaries=[{"start_page": 1, "end_page": 2}],
            extracted_docs=[
                {
                    "start_seite": 1,
                    "end_seite": 2,
                    "netto": 100.01, # within tolerance
                    "steuer": 19.0,
                    "brutto": 119.0
                }
            ],
            cache_hits_before=1,
            cache_misses_before=1,
            error=None
        )
    ]

    metrics = calculate_metrics(results, expected)

    assert metrics["exact_boundary_precision"] == 1.0
    assert metrics["exact_boundary_recall"] == 1.0
    assert metrics["start_page_accuracy"] == 1.0
    assert metrics["end_page_accuracy"] == 1.0
    assert metrics["net_amount_accuracy"] == 1.0
    assert metrics["tax_amount_accuracy"] == 1.0
    assert metrics["gross_amount_accuracy"] == 1.0
    assert metrics["amount_all_correct_rate"] == 1.0
    assert metrics["cache_hit_rate"] == 0.5
    assert metrics["avg_seconds_per_page"] == 0.75

def test_missing_ground_truth():
    results = [
        BenchmarkResult(
            filename="test.pdf",
            runtime_inspect=1.0,
            runtime_analysis=0.5,
            boundaries=[{"start_page": 1, "end_page": 1}],
            extracted_docs=[{"start_seite": 1, "end_seite": 1}],
            cache_hits_before=1,
            cache_misses_before=0
        )
    ]
    metrics = calculate_metrics(results, [])
    assert metrics["exact_boundary_precision"] == "not_available"


def test_no_data_mutation_and_fixture_mode():
    # Simple check that we can instantiate the evaluator in fixture mode
    # and it does not write to rag_index.db or anything globally unless told to.

    # We create a dummy test environment.
    evaluator = BenchmarkEvaluator(
        mode="fixture",
        fixture_extractor=lambda pages: {
            "belegtyp": "FIXTURE", "netto": 10.0, "steuer": 1.9,
            "brutto": 11.9, "lieferant": "Test", "datum": "2024-01-01",
            "rechnungsnummer": "FIXTURE-1",
        },
    )

    # Check states before
    paths_to_check = {
        "rag": Path("data/rag_index.db"),
        "vector": Path("data/vectorstore/index.json"),
        "wiki": Path("data/wiki"),
        "checkpoint": Path("data/checkpoint.json")
    }
    mtimes_before = {}
    for name, p in paths_to_check.items():
        if p.exists():
            mtimes_before[name] = p.stat().st_mtime
        else:
            mtimes_before[name] = None

    # We bypass pdf engine and analyzer by mocking in testing.
    # To truly mock it:
    class MockPDFEngine:
        def inspect_pdf(self, path):
            return [{"page_num": 1, "full_text": "Fixture text", "ocr_status": "TEXT_LAYER"}]
        def calculate_md5(self, path):
            return "dummy_md5"

    class MockAnalyzer:
        def detect_boundaries(self, pages):
            return [{"start_page": 1, "end_page": 1}]

    evaluator.pdf_engine = MockPDFEngine()
    evaluator.document_analyzer = MockAnalyzer()
    evaluator.rag_engine = type("ReadOnlyEmptyRAG", (), {"search": lambda *args, **kwargs: []})()

    # create a dummy pdf just so Path.name doesn't fail
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = Path(f.name)
        mtime_pdf_before = pdf_path.stat().st_mtime

    try:
        res = evaluator.evaluate_pdf(pdf_path)

        assert res.extracted_docs[0]["belegtyp"] == "FIXTURE"

        # Check nothing mutated
        for name, p in paths_to_check.items():
            if mtimes_before[name] is not None:
                assert p.stat().st_mtime == mtimes_before[name], f"{p} was mutated!"

        assert pdf_path.stat().st_mtime == mtime_pdf_before, "Input PDF was mutated!"
    finally:
        os.unlink(pdf_path)


def test_missing_pdf_directory():
    import subprocess
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run([sys.executable, "src/core/benchmark_document_pipeline.py", "invalid_dir", "--output", tmpdir], capture_output=True, text=True)
        assert result.returncode == 0
        assert "benchmark_summary.json" in os.listdir(tmpdir)
        with open(os.path.join(tmpdir, "benchmark_summary.json"), "r") as f:
            summary = json.load(f)
            assert summary["status"] == "success"
            assert summary["message"] == "No PDFs found."
