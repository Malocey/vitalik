"""End-to-End-Prüfung der SQLite-FTS5-Persistenz für Belege."""

import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.rag_engine import rag_engine
from src.wiki.wiki_engine import KarpathyLLMWikiEngine


def test_rag_persistence() -> None:
    marker = f"Persistenztest{uuid4().hex}"
    beleg_id = f"TEST-{uuid4().hex}"
    doc_data = {
        "lieferant": marker,
        "datum": "2026-07-21",
        "brutto": "123.45",
        "raw_text": None,
    }

    rag_engine.index_beleg(doc_data, beleg_id)

    # Eine eigene Verbindung wird bewusst geöffnet, geschlossen und neu geöffnet.
    first_connection = sqlite3.connect(rag_engine.db_path)
    first_connection.close()

    reopened_connection = sqlite3.connect(rag_engine.db_path)
    try:
        results = reopened_connection.execute(
            """
            SELECT beleg_id
            FROM belege_fts
            WHERE belege_fts MATCH ?
            """,
            (marker,),
        ).fetchall()
        assert len(results) > 0, "FTS5-Eintrag war nach erneutem Öffnen nicht persistent."
    finally:
        reopened_connection.execute(
            "DELETE FROM belege_fts WHERE beleg_id = ?",
            (beleg_id,),
        )
        reopened_connection.execute(
            "DELETE FROM belege WHERE beleg_id = ?",
            (beleg_id,),
        )
        reopened_connection.commit()
        reopened_connection.close()

    print(f"RAG-Persistenztest erfolgreich: {beleg_id}")


def test_wiki_markdown_and_rag_sync() -> None:
    beleg_id = f"TEST-WIKI-{uuid4().hex}"
    marker = f"WikiPersistenztest{uuid4().hex}"
    doc_data = {
        "lieferant": marker,
        "datum": "2026-07-21",
        "brutto": "234.56",
        "raw_text": None,
        "validation_status": "PASSED",
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        wiki = KarpathyLLMWikiEngine(Path(temp_dir) / "nested" / "wiki")
        with patch("src.wiki.wiki_engine.rag_engine.index_document") as index_document:
            page_path = wiki.create_or_update_beleg_page(doc_data, beleg_id)

        assert page_path.exists(), "Die Beleg-Markdown-Datei wurde nicht geschrieben."
        markdown = page_path.read_text(encoding="utf-8")
        assert beleg_id in markdown
        assert marker in markdown
        assert "Bruttobetrag:** 234.56 EUR" in markdown
        assert "## Zusammenfassung" in markdown
        assert "## Indizierungstext" not in markdown
        assert index_document.call_count == 3, (
            "Wiki-Seite, Wiki-Index und Wiki-Log wurden nicht vollständig ins RAG synchronisiert."
        )

        raw_path = Path(doc_data["raw_text_path"])
        if raw_path.exists():
            raw_path.unlink()

    print(f"Wiki-/RAG-Synchronisierung erfolgreich: {beleg_id}")


if __name__ == "__main__":
    test_rag_persistence()
    test_wiki_markdown_and_rag_sync()
