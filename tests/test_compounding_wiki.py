from pathlib import Path

import sqlite3

from src.core.compact_knowledge_wiki import analyze, apply_compaction
from src.wiki.wiki_engine import KarpathyLLMWikiEngine


class FakeRag:
    def __init__(self):
        self.documents = []

    def index_document(self, **document):
        self.documents = [item for item in self.documents if item["doc_id"] != document["doc_id"]]
        self.documents.append(document)

    def save_index(self):
        return None


def test_same_supplier_updates_one_hub_page(tmp_path: Path):
    rag = FakeRag()
    wiki = KarpathyLLMWikiEngine(tmp_path / "wiki", rag=rag)
    first = {"lieferant": "Jensmann GmbH", "datum": "2026-01-01", "brutto": 10,
             "beleg_link": "/docs/1.pdf", "warengruppe": "Fleischwaren"}
    second = {"lieferant": "Jensmann GmbH", "datum": "2026-02-01", "brutto": 20,
              "beleg_link": "/docs/2.pdf", "warengruppe": "Fleischwaren"}

    page_one = wiki.update_contact_page(first, "VG-1")
    page_two = wiki.update_contact_page(second, "VG-2")

    assert page_one == page_two
    assert len(list((tmp_path / "wiki" / "entities" / "suppliers").glob("*.md"))) == 1
    text = page_one.read_text(encoding="utf-8")
    assert "source_count: 2" in text
    assert text.count("`VG-1`") == 1
    assert text.count("`VG-2`") == 1
    assert not list((tmp_path / "wiki").glob("beleg_*.md"))


def test_reprocessing_source_is_idempotent(tmp_path: Path):
    wiki = KarpathyLLMWikiEngine(tmp_path / "wiki", rag=FakeRag())
    doc = {"lieferant": "Jensmann", "datum": "2026-01-01", "brutto": 10}
    page = wiki.update_contact_page(doc, "VG-1")
    wiki.update_contact_page(doc, "VG-1")
    assert page.read_text(encoding="utf-8").count("`VG-1`") == 1
    assert "source_count: 1" in page.read_text(encoding="utf-8")


def test_graph_excludes_archived_receipt_pages(tmp_path: Path):
    wiki = KarpathyLLMWikiEngine(tmp_path / "wiki", rag=FakeRag())
    wiki.update_contact_page({"lieferant": "Jensmann"}, "VG-1")
    archive = tmp_path / "wiki" / "archive" / "belege"
    archive.mkdir(parents=True)
    (archive / "beleg_old.md").write_text("# Alter Beleg", encoding="utf-8")
    graph = wiki.get_graph_data()
    assert "beleg_old" not in {node["id"] for node in graph["nodes"]}


def test_dry_run_reports_compaction_without_writes(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "beleg_1.md").write_text("one", encoding="utf-8")
    (wiki / "beleg_2.md").write_text("two", encoding="utf-8")
    rows = [
        {"beleg_id": "1", "lieferant": "Jensmann", "rechnungsnummer": "A",
         "datum": "2026-01-01", "brutto": 10},
        {"beleg_id": "2", "lieferant": "Jensmann", "rechnungsnummer": "B",
         "datum": "2026-01-02", "brutto": 20},
    ]
    report = analyze(rows, wiki)
    assert report["old_beleg_pages"] == 2
    assert report["canonical_supplier_pages"] == 1
    assert report["pages_saved"] == 1
    assert len(list(wiki.glob("beleg_*.md"))) == 2


def test_dry_run_never_treats_workflow_page_as_receipt(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "beleg_1.md").write_text("receipt", encoding="utf-8")
    workflow = wiki / "beleg_pipeline_anleitung.md"
    workflow.write_text("workflow", encoding="utf-8")
    report = analyze([{"beleg_id": "1", "lieferant": "Jensmann"}], wiki)
    assert report["old_beleg_pages"] == 1
    assert workflow.read_text(encoding="utf-8") == "workflow"


def test_apply_makes_backup_archives_sources_and_updates_database(tmp_path: Path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "beleg_1.md").write_text("legacy", encoding="utf-8")
    db_path = tmp_path / "rag.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE belege (beleg_id TEXT PRIMARY KEY, lieferant TEXT, datum TEXT, "
                   "brutto REAL, rechnungsnummer TEXT, contact_entity_id TEXT, status TEXT, "
                   "skr_konto TEXT, wiki_path TEXT, updated_at TEXT)")
        db.execute("INSERT INTO belege VALUES ('1','Jensmann','2026-01-01',10,'R1','E1',"
                   "'PASSED','3400','old',CURRENT_TIMESTAMP)")
    rag = FakeRag()
    rag.documents = [{"doc_id": "wiki_beleg_1"}]
    wiki = KarpathyLLMWikiEngine(wiki_dir, rag=rag)

    report = apply_compaction(db_path, wiki_dir, tmp_path / "backup", wiki, rag)

    assert report["archived_pages"] == 1
    assert (wiki_dir / "archive" / "belege" / "beleg_1.md").exists()
    hub = wiki_dir / "entities" / "suppliers" / "jensmann.md"
    assert hub.exists()
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT wiki_path FROM belege WHERE beleg_id='1'").fetchone()[0] == str(hub)
    assert not any(item.get("doc_id") == "wiki_beleg_1" for item in rag.documents)
    assert Path(report["backup"]).joinpath("rag_index.db").exists()
