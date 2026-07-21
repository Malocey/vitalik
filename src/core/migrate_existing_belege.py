"""Reichert bereits indexierte Belege nachträglich mit sevDesk-Stammdaten an."""

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.rag_engine import rag_engine
from src.parser.analyzer import document_analyzer
from src.wiki.wiki_engine import wiki_engine


def migrate_existing_belege() -> dict:
    with sqlite3.connect(rag_engine.db_path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM belege WHERE beleg_id NOT LIKE 'TEST-%'").fetchall()

    migrated = 0
    supplier_matches = 0
    article_matches = 0
    for row in rows:
        doc = dict(row)
        doc["validation_status"] = doc.get("status", "")
        doc["steuersatz_prozent"] = doc.get("ust_satz")
        raw_path = Path(doc.get("raw_text_path") or "")
        raw_text = raw_path.read_text(encoding="utf-8", errors="replace") if raw_path.is_file() else ""
        doc["raw_text"] = raw_text
        assignment = rag_engine.match_sevdesk_assignment(raw_text)
        doc = document_analyzer._apply_sevdesk_assignment(doc, assignment)
        if assignment.get("supplier"):
            supplier_matches += 1
        article_matches += len(assignment.get("articles") or [])
        wiki_engine.create_or_update_beleg_page(doc, doc["beleg_id"])
        rag_engine.index_beleg(doc, doc["beleg_id"])
        migrated += 1

    return {
        "migrated": migrated,
        "supplier_matches": supplier_matches,
        "article_matches": article_matches,
    }


if __name__ == "__main__":
    result = migrate_existing_belege()
    print(
        f"Migration erfolgreich: {result['migrated']} Belege, "
        f"{result['supplier_matches']} Lieferantenmatches, "
        f"{result['article_matches']} Artikelmatches"
    )
