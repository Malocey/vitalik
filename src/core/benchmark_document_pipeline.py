import argparse
import csv
import json
import logging
import time
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.benchmark_evaluator import BenchmarkEvaluator, BenchmarkResult

# Wir loggen alles vom Benchmark mit auf die Konsole
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Benchmark")


def parse_args():
    parser = argparse.ArgumentParser(description="Automatisertes Qualitäts- und Benchmark-System für die Belegerkennung.")
    parser.add_argument("pdf_dir", type=str, help="Pfad zum Verzeichnis mit den PDF-Dateien.")
    parser.add_argument("--expected", type=str, help="Pfad zur CSV-Datei mit den erwarteten Ground-Truth-Daten (Optional).", default=None)
    parser.add_argument("--output", type=str, help="Ausgabeverzeichnis für die Berichte.", default="data/reports/benchmark")
    parser.add_argument("--mode", type=str, choices=["structural", "fixture", "live"], default="structural", help="Betriebsart: structural (ohne KI, regex), fixture (mocked), live (mit LLM)")
    return parser.parse_args()


def load_expected_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """Lädt die Erwartungsdaten und normalisiert Zahlen (Komma zu Punkt) etc."""
    expected_data = []
    if not csv_path.exists():
        logger.warning(f"CSV-Datei nicht gefunden: {csv_path}")
        return expected_data

    try:
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                norm_row = {}
                for key, val in row.items():
                    key = key.strip().lower() if key else ""
                    val = val.strip() if val else ""

                    if key in ["netto", "steuer", "brutto"]:
                        if val:
                            try:
                                # Wandle Komma in Punkt um, entferne Tausenderpunkte falls vorhanden (vereinfacht)
                                val_norm = val.replace(".", "").replace(",", ".") if "," in val and "." in val else val.replace(",", ".")
                                norm_row[key] = float(val_norm)
                            except ValueError:
                                norm_row[key] = None
                        else:
                            norm_row[key] = None
                    elif key in ["startseite", "endseite"]:
                        norm_row[key] = int(val) if val.isdigit() else None
                    else:
                        norm_row[key] = val
                expected_data.append(norm_row)
    except Exception as e:
        logger.error(f"Fehler beim Laden der CSV {csv_path}: {e}")

    return expected_data

def init_output_dir(output_dir: str) -> Path:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    return out_path

def generate_empty_report(output_dir: Path):
    """Erzeugt leere (not_available) Berichte für den Fall, dass keine PDFs vorhanden sind."""
    summary = {
        "status": "success",
        "message": "No PDFs found.",
        "total_pdfs": 0,
        "total_documents_extracted": 0,
        "metrics": {
            "exact_boundary_precision": "not_available",
            "exact_boundary_recall": "not_available",
            "start_page_accuracy": "not_available",
            "end_page_accuracy": "not_available",
            "page_assignment_accuracy": "not_available",
            "net_amount_accuracy": "not_available",
            "tax_amount_accuracy": "not_available",
            "gross_amount_accuracy": "not_available",
            "manual_check_share": "not_available",
            "llm_calls_per_document": "not_available",
        }
    }

    with open(output_dir / "benchmark_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    with open(output_dir / "benchmark_results.csv", "w", encoding="utf-8") as f:
        f.write("dateiname;status\n")

    with open(output_dir / "benchmark_report.md", "w", encoding="utf-8") as f:
        f.write("# Benchmark Report\n\nNo PDFs found in the given directory.\n")


def calculate_metrics(results: List[BenchmarkResult], expected: List[Dict[str, Any]]):
    """Berechnet die Metriken aus den Ergebnissen."""
    metrics = {
        "exact_boundary_precision": "not_available",
        "exact_boundary_recall": "not_available",
        "start_page_accuracy": "not_available",
        "end_page_accuracy": "not_available",
        "page_assignment_accuracy": "not_available",
        "net_amount_accuracy": "not_available",
        "tax_amount_accuracy": "not_available",
        "gross_amount_accuracy": "not_available",
        "supplier_hit_rate": "not_available",
        "document_type_hit_rate": "not_available",
        "invoice_number_hit_rate": "not_available",
        "amount_all_correct_rate": "not_available",
        "mean_absolute_error": "not_available",
        "median_absolute_error": "not_available",
        "cache_hit_rate": "not_available",
        "avg_seconds_per_page": "not_available",
        "manual_check_share": "not_available",
        "llm_calls_per_document": "not_available",
    }

    total_cache_hits = sum(r.cache_hits_before for r in results)
    total_cache_misses = sum(r.cache_misses_before for r in results)
    if total_cache_hits + total_cache_misses > 0:
        metrics["cache_hit_rate"] = total_cache_hits / (total_cache_hits + total_cache_misses)

    total_pages = total_cache_hits + total_cache_misses
    total_time = sum(r.runtime_inspect + r.runtime_analysis for r in results)
    if total_pages > 0:
        metrics["avg_seconds_per_page"] = total_time / total_pages

    # Count manual checks needed (e.g., if there's an error or low confidence)
    total_docs_extracted = sum(len(r.extracted_docs) for r in results)
    manual_checks = 0
    total_llm_calls = 0
    for res in results:
        for doc in res.extracted_docs:
            if doc.get("error") or doc.get("confidence_score", 1.0) < 0.8:
                manual_checks += 1
            calls = doc.get("llm_calls")
            if isinstance(calls, int):
                total_llm_calls += calls

    if total_docs_extracted > 0:
        metrics["manual_check_share"] = manual_checks / total_docs_extracted
        known_llm_docs = sum(
            1 for result in results for doc in result.extracted_docs
            if isinstance(doc.get("llm_calls"), int)
        )
        if known_llm_docs == total_docs_extracted:
            metrics["llm_calls_per_document"] = total_llm_calls / total_docs_extracted

    if not expected:
        return metrics

    # Group expected by filename
    exp_by_file = {}
    for e in expected:
        fname = e.get("dateiname", "")
        if fname not in exp_by_file:
            exp_by_file[fname] = []
        exp_by_file[fname].append(e)

    exact_matches = 0
    total_expected = len(expected)
    total_detected = sum(len(r.boundaries) for r in results)

    start_correct = 0
    end_correct = 0

    pages_assigned_correctly = 0
    total_pages_evaluated = 0

    net_correct, net_total = 0, 0
    tax_correct, tax_total = 0, 0
    gross_correct, gross_total = 0, 0
    amount_all_correct = 0
    amount_evaluations = 0

    supplier_correct, supplier_total = 0, 0
    type_correct, type_total = 0, 0
    inv_correct, inv_total = 0, 0

    errors = []

    for res in results:
        fname = res.filename
        exp_list = exp_by_file.get(fname, [])

        # Exact Boundaries
        det_bounds = [(b["start_page"], b["end_page"]) for b in res.boundaries]
        exp_bounds = [(e.get("startseite"), e.get("endseite")) for e in exp_list if e.get("startseite") is not None and e.get("endseite") is not None]

        for det in det_bounds:
            if det in exp_bounds:
                exact_matches += 1

        for e in exp_bounds:
            start_e, end_e = e
            # find closest detected
            for d in det_bounds:
                start_d, end_d = d
                if start_e == start_d:
                    start_correct += 1
                if end_e == end_d:
                    end_correct += 1

        # Page assignment
        if exp_bounds:
            max_page = max(max(e) for e in exp_bounds)
            for p in range(1, max_page + 1):
                exp_assign = next((i for i, (s, e) in enumerate(exp_bounds) if s <= p <= e), -1)
                det_assign = next((i for i, (s, e) in enumerate(det_bounds) if s <= p <= e), -1)

                # We simply check if the page is mapped to the SAME relative document index.
                # A more robust check might match documents, but this works for basic sequential evaluation.
                if exp_assign == det_assign and exp_assign != -1:
                    pages_assigned_correctly += 1
                total_pages_evaluated += 1

        # Data extraction evaluation (simple matching by start_page)
        for doc in res.extracted_docs:
            start = doc.get("start_seite")
            # find matching expected
            match = next((e for e in exp_list if e.get("startseite") == start), None)
            if not match:
                continue

            # Amounts
            def eval_amount(val_det, val_exp, correct_count, total_count):
                if val_exp is not None:
                    total_count += 1
                    if val_det is not None and abs(float(val_det) - float(val_exp)) <= 0.02:
                        correct_count += 1
                    if val_det is not None:
                        errors.append(abs(float(val_det) - float(val_exp)))
                return correct_count, total_count

            n_c = net_correct
            t_c = tax_correct
            g_c = gross_correct

            net_correct, net_total = eval_amount(doc.get("netto"), match.get("netto"), net_correct, net_total)
            tax_correct, tax_total = eval_amount(doc.get("steuer"), match.get("steuer"), tax_correct, tax_total)
            gross_correct, gross_total = eval_amount(doc.get("brutto"), match.get("brutto"), gross_correct, gross_total)

            amount_evaluations += 1
            if (net_correct > n_c or match.get("netto") is None) and \
               (tax_correct > t_c or match.get("steuer") is None) and \
               (gross_correct > g_c or match.get("brutto") is None):
                amount_all_correct += 1

            # strings
            if match.get("lieferant"):
                supplier_total += 1
                if doc.get("lieferant", "").lower() == match.get("lieferant").lower():
                    supplier_correct += 1

            if match.get("dokumenttyp"):
                type_total += 1
                if doc.get("belegtyp", "").lower() == match.get("dokumenttyp").lower():
                    type_correct += 1

            if match.get("rechnungsnummer"):
                inv_total += 1
                if doc.get("rechnungsnummer", "").lower() == match.get("rechnungsnummer").lower():
                    inv_correct += 1


    if total_detected > 0:
        metrics["exact_boundary_precision"] = exact_matches / total_detected
    if total_expected > 0:
        metrics["exact_boundary_recall"] = exact_matches / total_expected
        metrics["start_page_accuracy"] = start_correct / total_expected
        metrics["end_page_accuracy"] = end_correct / total_expected

    if total_pages_evaluated > 0:
        metrics["page_assignment_accuracy"] = pages_assigned_correctly / total_pages_evaluated

    if net_total > 0: metrics["net_amount_accuracy"] = net_correct / net_total
    if tax_total > 0: metrics["tax_amount_accuracy"] = tax_correct / tax_total
    if gross_total > 0: metrics["gross_amount_accuracy"] = gross_correct / gross_total
    if amount_evaluations > 0: metrics["amount_all_correct_rate"] = amount_all_correct / amount_evaluations

    if supplier_total > 0: metrics["supplier_hit_rate"] = supplier_correct / supplier_total
    if type_total > 0: metrics["document_type_hit_rate"] = type_correct / type_total
    if inv_total > 0: metrics["invoice_number_hit_rate"] = inv_correct / inv_total

    if errors:
        metrics["mean_absolute_error"] = sum(errors) / len(errors)
        errors.sort()
        mid = len(errors) // 2
        metrics["median_absolute_error"] = (errors[mid] + errors[~mid]) / 2.0

    return metrics

def write_reports(results: List[BenchmarkResult], metrics: Dict[str, Any], output_dir: Path):
    """Schreibt die JSON, CSV und Markdown Reports."""

    # JSON Summary
    summary = {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "total_pdfs": len(results),
        "total_documents_extracted": sum(len(r.extracted_docs) for r in results),
        "metrics": metrics
    }
    with open(output_dir / "benchmark_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # CSV
    with open(output_dir / "benchmark_results.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "dateiname", "startseite", "endseite", "error", "llm_worker",
            "lieferant", "belegtyp", "rechnungsnummer", "netto", "steuer", "brutto",
            "ocr_character_count", "ocr_quality_score", "math_consistent",
            "rag_hits_count", "rag_search_time", "rag_doc_ids", "rag_categories", "rag_sources", "rag_scores", "llm_calls"
        ])
        for res in results:
            if not res.extracted_docs:
                writer.writerow([res.filename, "", "", res.error or "NO_DOCS", res.llm_worker, "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])
            for doc in res.extracted_docs:
                writer.writerow([
                    res.filename,
                    doc.get("start_seite", ""),
                    doc.get("end_seite", ""),
                    doc.get("error", res.error or ""),
                    res.llm_worker,
                    doc.get("lieferant", ""),
                    doc.get("belegtyp", ""),
                    doc.get("rechnungsnummer", ""),
                    doc.get("netto", ""),
                    doc.get("steuer", ""),
                    doc.get("brutto", ""),
                    doc.get("ocr_character_count", 0),
                    doc.get("ocr_quality_score", 1.0),
                    doc.get("math_consistent", False),
                    doc.get("rag_hits_count", 0),
                    doc.get("rag_search_time", 0.0),
                    ",".join(map(str, doc.get("rag_doc_ids", []))),
                    ",".join(map(str, doc.get("rag_categories", []))),
                    ",".join(map(str, doc.get("rag_sources", []))),
                    ",".join(map(str, doc.get("rag_scores", []))),
                    doc.get("llm_calls", 0)
                ])

    # MD
    with open(output_dir / "benchmark_report.md", "w", encoding="utf-8") as f:
        f.write("# Document Quality Benchmark Report\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**PDFs processed:** {len(results)}\n")
        f.write(f"**Documents extracted:** {sum(len(r.extracted_docs) for r in results)}\n\n")
        f.write("## Metrics\n\n")
        for k, v in metrics.items():
            if isinstance(v, float):
                f.write(f"- **{k}**: {v:.4f}\n")
            else:
                f.write(f"- **{k}**: {v}\n")


def main():
    args = parse_args()
    pdf_dir = Path(args.pdf_dir)
    output_dir = init_output_dir(args.output)

    logger.info(f"Starte Benchmark im Modus: {args.mode}")
    logger.info(f"Lese PDF-Verzeichnis: {pdf_dir}")

    if not pdf_dir.exists() or not pdf_dir.is_dir():
        logger.error(f"PDF-Verzeichnis existiert nicht: {pdf_dir}")
        generate_empty_report(output_dir)
        return

    pdf_files = list(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        logger.info("Keine PDF-Dateien im Verzeichnis gefunden.")
        generate_empty_report(output_dir)
        return

    expected_data = []
    if args.expected:
        expected_csv = Path(args.expected)
        expected_data = load_expected_csv(expected_csv)
        logger.info(f"{len(expected_data)} Ground-Truth-Datensätze geladen.")

    evaluator = BenchmarkEvaluator(mode=args.mode)
    results = []

    for pdf_file in pdf_files:
        res = evaluator.evaluate_pdf(pdf_file)
        results.append(res)

    metrics = calculate_metrics(results, expected_data)
    write_reports(results, metrics, output_dir)
    logger.info(f"Benchmark beendet. Ergebnisse in {output_dir}")


if __name__ == "__main__":
    main()
