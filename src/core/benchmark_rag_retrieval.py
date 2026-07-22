import argparse
import json
import csv
import sys
import logging
import tempfile
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict
from dataclasses import dataclass
import time

from src.core.rag_engine import rag_engine as global_rag_engine, RAGEngine
from src.core.local_llm_client import LocalLLMClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("RAGBenchmark")

@dataclass
class GroundTruthItem:
    query_id: str
    query: str
    query_type: str
    expected_entity_id: Optional[str]
    expected_doc_ids: List[str]
    allowed_categories: List[str]
    expected_sources: List[str]

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            query_id=data["query_id"],
            query=data["query"],
            query_type=data["query_type"],
            expected_entity_id=data.get("expected_entity_id"),
            expected_doc_ids=data.get("expected_doc_ids", []),
            allowed_categories=data.get("allowed_categories", []),
            expected_sources=data.get("expected_sources", [])
        )

def load_ground_truth(path: Path) -> List[GroundTruthItem]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(GroundTruthItem.from_dict(json.loads(line)))
    return items

def calculate_metrics(results: List[Dict[str, Any]], thresholds: Dict[str, float]) -> Dict[str, Any]:
    metrics = {
        "overall": {
            "total_queries": len(results),
            "hit@1": 0.0,
            "hit@3": 0.0,
            "hit@5": 0.0,
            "mrr": 0.0,
            "duplicate_query_rate@5": 0.0,
            "false_entity_rate": 0.0,
            "entity_miss_rate": 0.0,
            "exact_supplier_hub_first_rate": 0.0,
        },
        "by_type": defaultdict(lambda: {
            "total_queries": 0,
            "hit@1": 0.0,
            "hit@3": 0.0,
            "hit@5": 0.0,
            "mrr": 0.0,
        }),
        "sources": defaultdict(int),
        "source_hit_rates": {
            "fts5_hits": 0,
            "ocr_fallback_hits": 0,
            "ocr_fallback_usage": 0,
            "correct_only_by_ocr": 0,
        }
    }

    if not results:
        return metrics

    hits_at_1 = 0
    hits_at_3 = 0
    hits_at_5 = 0
    mrr_sum = 0.0
    duplicates = 0

    entity_queries = 0
    false_entities = 0
    entity_misses = 0
    exact_supplier_hub_first = 0

    for res in results:
        gt: GroundTruthItem = res["ground_truth"]
        retrieved = res["retrieved"]
        q_type = gt.query_type

        metrics["by_type"][q_type]["total_queries"] += 1

        expected_docs = set(gt.expected_doc_ids)
        expected_entity = gt.expected_entity_id

        # calculate hits
        hit_positions = []
        seen_docs = set()
        has_duplicate = False

        first_entity_hit = None

        for i, doc in enumerate(retrieved[:5]):
            doc_id = doc.get("doc_id")
            source = doc.get("source")
            category = doc.get("category")

            if category not in gt.allowed_categories and category and gt.allowed_categories:
                logger.debug(f"Retrieved doc {doc_id} has unallowed category {category}")
            if source not in gt.expected_sources and source and gt.expected_sources:
                logger.debug(f"Retrieved doc {doc_id} has unexpected source {source}")

            metrics["sources"][source] += 1

            if doc_id in seen_docs:
                has_duplicate = True
            seen_docs.add(doc_id)

            if expected_entity and doc_id == expected_entity:
                hit_positions.append(i + 1)
            elif expected_docs and doc_id in expected_docs:
                hit_positions.append(i + 1)

            if expected_entity and str(category).startswith("wiki_") and first_entity_hit is None:
                first_entity_hit = doc_id

        if has_duplicate:
            duplicates += 1

        if q_type == "entity":
            entity_queries += 1
            if first_entity_hit is None:
                entity_misses += 1
            elif first_entity_hit != expected_entity:
                false_entities += 1

            if retrieved and retrieved[0].get("doc_id") == expected_entity:
                # check if subsequent are unique
                subsequent_docs = [d.get("doc_id") for d in retrieved[1:]]
                if len(subsequent_docs) == len(set(subsequent_docs)):
                    exact_supplier_hub_first += 1

        first_hit_rank = min(hit_positions) if hit_positions else 0

        if first_hit_rank > 0:
            mrr_sum += 1.0 / first_hit_rank
            metrics["by_type"][q_type]["mrr"] += 1.0 / first_hit_rank
            if first_hit_rank <= 1:
                hits_at_1 += 1
                metrics["by_type"][q_type]["hit@1"] += 1
            if first_hit_rank <= 3:
                hits_at_3 += 1
                metrics["by_type"][q_type]["hit@3"] += 1
            if first_hit_rank <= 5:
                hits_at_5 += 1
                metrics["by_type"][q_type]["hit@5"] += 1

        # Source metrics
        has_fts5 = any(d.get("source") == "fts5" and (d.get("doc_id") in expected_docs or d.get("doc_id") == expected_entity) for d in retrieved)
        has_ocr = any(d.get("source") == "ocr_fallback" and (d.get("doc_id") in expected_docs or d.get("doc_id") == expected_entity) for d in retrieved)
        uses_ocr = any(d.get("source") == "ocr_fallback" for d in retrieved)

        if has_fts5: metrics["source_hit_rates"]["fts5_hits"] += 1
        if has_ocr: metrics["source_hit_rates"]["ocr_fallback_hits"] += 1
        if uses_ocr: metrics["source_hit_rates"]["ocr_fallback_usage"] += 1
        if has_ocr and not has_fts5: metrics["source_hit_rates"]["correct_only_by_ocr"] += 1


    total = len(results)
    metrics["overall"]["hit@1"] = hits_at_1 / total
    metrics["overall"]["hit@3"] = hits_at_3 / total
    metrics["overall"]["hit@5"] = hits_at_5 / total
    metrics["overall"]["mrr"] = mrr_sum / total
    metrics["overall"]["duplicate_query_rate@5"] = duplicates / total

    if entity_queries > 0:
        metrics["overall"]["false_entity_rate"] = false_entities / entity_queries
        metrics["overall"]["entity_miss_rate"] = entity_misses / entity_queries
        metrics["overall"]["exact_supplier_hub_first_rate"] = exact_supplier_hub_first / entity_queries

    for q_type, type_metrics in metrics["by_type"].items():
        type_total = type_metrics["total_queries"]
        if type_total > 0:
            type_metrics["hit@1"] /= type_total
            type_metrics["hit@3"] /= type_total
            type_metrics["hit@5"] /= type_total
            type_metrics["mrr"] /= type_total

    metrics["source_hit_rates"]["fts5_hit_rate"] = metrics["source_hit_rates"]["fts5_hits"] / total
    metrics["source_hit_rates"]["ocr_fallback_hit_rate"] = metrics["source_hit_rates"]["ocr_fallback_hits"] / total
    metrics["source_hit_rates"]["ocr_fallback_usage_rate"] = metrics["source_hit_rates"]["ocr_fallback_usage"] / total

    return metrics

def export_results(results: List[Dict[str, Any]], metrics: Dict[str, Any], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    with open(output_dir / "benchmark_rag_results.json", "w", encoding="utf-8") as f:
        json.dump({"metrics": metrics, "results": [{"query_id": r["ground_truth"].query_id, "retrieved": [d.get("doc_id") for d in r["retrieved"]]} for r in results]}, f, indent=2)

    # CSV
    with open(output_dir / "benchmark_rag_results.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["query_id", "query", "query_type", "expected_entity", "expected_docs", "retrieved_docs", "sources"])
        for r in results:
            gt = r["ground_truth"]
            writer.writerow([
                gt.query_id, gt.query, gt.query_type, gt.expected_entity_id or "",
                ",".join(gt.expected_doc_ids), ",".join([d.get("doc_id", "") for d in r["retrieved"]]),
                ",".join([d.get("source", "") for d in r["retrieved"]])
            ])

    # Markdown
    with open(output_dir / "benchmark_rag_report.md", "w", encoding="utf-8") as f:
        f.write("# RAG Retrieval Benchmark Report\n\n")
        f.write("## Overall Metrics\n")
        for k, v in metrics["overall"].items():
            f.write(f"- **{k}**: {v:.4f}\n" if isinstance(v, float) else f"- **{k}**: {v}\n")

        f.write("\n## By Query Type\n")
        for q_type, type_metrics in metrics["by_type"].items():
            f.write(f"### {q_type}\n")
            for k, v in type_metrics.items():
                f.write(f"- **{k}**: {v:.4f}\n" if isinstance(v, float) else f"- **{k}**: {v}\n")

        f.write("\n## Sources\n")
        for k, v in metrics["source_hit_rates"].items():
            f.write(f"- **{k}**: {v:.4f}\n" if isinstance(v, float) else f"- **{k}**: {v}\n")

def check_thresholds(metrics: Dict[str, Any], thresholds: Dict[str, float]) -> bool:
    passed = True
    overall = metrics["overall"]

    checks = [
        ("hit@1", overall["hit@1"], thresholds["hit@1"], lambda v, t: v >= t),
        ("hit@3", overall["hit@3"], thresholds["hit@3"], lambda v, t: v >= t),
        ("hit@5", overall["hit@5"], thresholds["hit@5"], lambda v, t: v >= t),
        ("mrr", overall["mrr"], thresholds["mrr"], lambda v, t: v >= t),
        ("duplicate_query_rate@5", overall["duplicate_query_rate@5"], thresholds["duplicate_rate"], lambda v, t: v <= t),
        ("false_entity_rate", overall["false_entity_rate"], thresholds["false_entity_rate"], lambda v, t: v <= t),
        ("exact_supplier_hub_first_rate", overall["exact_supplier_hub_first_rate"], thresholds["supplier_hub_first_rate"], lambda v, t: v >= t),
    ]

    for name, val, thresh, comp in checks:
        if not comp(val, thresh):
            logger.error(f"Threshold failed for {name}: {val:.4f} (expected {thresh})")
            passed = False
        else:
            logger.info(f"Threshold passed for {name}: {val:.4f} (expected {thresh})")

    return passed

def run_benchmark(mode: str, ground_truth_path: Path, output_dir: Path, thresholds: Dict[str, float], engine: Optional[RAGEngine] = None) -> bool:
    try:
        ground_truth = load_ground_truth(ground_truth_path)
    except Exception as e:
        logger.error(f"Failed to load ground truth from {ground_truth_path}: {e}")
        return False

    logger.info(f"Loaded {len(ground_truth)} queries from {ground_truth_path}")

    valid_query_types = {"entity", "invoice_number", "date_range", "article_category", "amount", "accounting"}

    if mode == "structural":
        logger.info("Running in structural mode. Validating schema and consistency.")
        errors = 0
        for gt in ground_truth:
            if gt.query_type not in valid_query_types:
                logger.error(f"Invalid query_type '{gt.query_type}' for query '{gt.query_id}'")
                errors += 1
            if not gt.query_id or not gt.query:
                logger.error(f"Missing required fields for query '{gt.query_id}'")
                errors += 1

        if errors > 0:
            logger.error(f"Structural validation failed with {errors} errors.")
            return False

        logger.info("Structural validation passed.")
        return True

    elif mode == "fixture":
        logger.info("Running in fixture mode. Using offline engine with mock data.")

        # Mock embedding function for deterministic offline execution
        def mock_generate_embedding(text: str) -> List[float]:
            # Deterministic hash to vector mapping
            h = hashlib.md5(text.encode()).digest()
            return [(b / 255.0) for b in h] + [0.0] * (384 - 16)

        mock_llm_client = LocalLLMClient()
        mock_llm_client.generate_embedding = mock_generate_embedding

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            test_engine = RAGEngine(llm_client=mock_llm_client)
            test_engine.db_path = temp_dir_path / "mock_rag.db"
            test_engine.index_file = temp_dir_path / "mock_index.json"
            test_engine._init_sqlite_db()

            # Populate mock db
            for gt in ground_truth:
                if gt.expected_entity_id:
                    test_engine.documents.append({
                        "doc_id": gt.expected_entity_id,
                        "title": gt.query,
                        "content": gt.query,
                        "category": "wiki_lieferant",
                        "source": "wiki",
                        "embedding": mock_generate_embedding(gt.query)
                    })
                for doc_id in gt.expected_doc_ids:
                    if "ocr_fallback" in gt.expected_sources and len(gt.expected_sources) == 1:
                        test_engine.index_beleg({"raw_text": gt.query, "lieferant": "", "datum": "", "brutto": ""}, doc_id)
                        # We force it out of FTS5 by blanking summary
                        import sqlite3
                        with sqlite3.connect(test_engine.db_path) as conn:
                            conn.execute("DELETE FROM belege_fts WHERE beleg_id = ?", (doc_id,))
                            conn.commit()
                    else:
                        test_engine.index_beleg({"raw_text": gt.query, "lieferant": gt.query}, doc_id)

            engine_to_use = test_engine

            results = []
            for gt in ground_truth:
                retrieved = engine_to_use.search(gt.query, top_k=5, use_fts=True)
                results.append({
                    "ground_truth": gt,
                    "retrieved": retrieved
                })

            metrics = calculate_metrics(results, thresholds)
            export_results(results, metrics, output_dir)

            passed = check_thresholds(metrics, thresholds)
            if not passed:
                logger.error("One or more thresholds failed.")
                return False

            logger.info("Benchmark completed successfully.")
            return True

    elif mode == "live":
        logger.info("Running in live mode with real RAGEngine.")
        engine_to_use = engine or global_rag_engine
        results = []
        for gt in ground_truth:
            retrieved = engine_to_use.search(gt.query, top_k=5, use_fts=True)
            results.append({
                "ground_truth": gt,
                "retrieved": retrieved
            })

        metrics = calculate_metrics(results, thresholds)
        export_results(results, metrics, output_dir)

        passed = check_thresholds(metrics, thresholds)
        if not passed:
            logger.error("One or more thresholds failed.")
            return False

        logger.info("Benchmark completed successfully.")
        return True

    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG Retrieval Benchmark")
    parser.add_argument("--mode", choices=["structural", "fixture", "live"], required=True)
    parser.add_argument("--ground_truth", type=str, required=True)
    parser.add_argument("--output", type=str, required=True)
    parser.add_argument("--hit1", type=float, default=0.80)
    parser.add_argument("--hit3", type=float, default=0.90)
    parser.add_argument("--hit5", type=float, default=0.95)
    parser.add_argument("--mrr", type=float, default=0.85)
    parser.add_argument("--duplicate_rate", type=float, default=0.0)
    parser.add_argument("--false_entity_rate", type=float, default=0.05)
    parser.add_argument("--supplier_hub_first_rate", type=float, default=1.0)

    args = parser.parse_args()

    thresholds = {
        "hit@1": args.hit1,
        "hit@3": args.hit3,
        "hit@5": args.hit5,
        "mrr": args.mrr,
        "duplicate_rate": args.duplicate_rate,
        "false_entity_rate": args.false_entity_rate,
        "supplier_hub_first_rate": args.supplier_hub_first_rate,
    }

    success = run_benchmark(args.mode, Path(args.ground_truth), Path(args.output), thresholds)
    if not success:
        sys.exit(1)
