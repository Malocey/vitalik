import pytest
import sqlite3
import json
import yaml
from pathlib import Path
from src.wiki.wiki_engine import KarpathyLLMWikiEngine

@pytest.fixture
def temp_wiki(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    engine = KarpathyLLMWikiEngine(wiki_dir=wiki_dir)
    return engine, wiki_dir

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "rag_index.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE belege (beleg_id TEXT PRIMARY KEY, beleg_link TEXT)")
    conn.execute("INSERT INTO belege (beleg_id) VALUES ('123')")
    conn.execute("INSERT INTO belege (beleg_id) VALUES ('456')")
    conn.commit()
    conn.close()
    return db_path

def test_recursive_discovery(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    sub_dir = wiki_dir / "entities" / "suppliers"
    sub_dir.mkdir(parents=True)

    # Valid frontmatter for supplier
    fm = {
        "entity_id": "sup1",
        "entity_type": "supplier",
        "canonical_name": "Supplier 1",
        "source_count": 0,
        "updated": "2023-10-01",
        "article_categories": ["food"],
        "skr03_accounts": ["3400"]
    }
    content = f"---\n{yaml.dump(fm)}---\n# Supplier 1\n"
    (sub_dir / "supplier_1.md").write_text(content, encoding="utf-8")

    report = engine.lint_wiki(db_path=temp_db)
    assert report["total_pages"] == 1
    assert "supplier_1.md" in report["orphan_pages"] # it has no links and is not index/log

def test_archive_exclusion(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    archive_dir = wiki_dir / "entities" / "archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "old_doc.md").write_text("# Old\n", encoding="utf-8")

    report = engine.lint_wiki(db_path=temp_db)
    assert report["total_pages"] == 0

def test_broken_markdown_link(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    content = "---\nentity_id: 1\nentity_type: konzept\ncanonical_name: A\nsource_count: 0\nupdated: '2'\n---\n[Broken](./missing.md)"
    (wiki_dir / "valid.md").write_text(content, encoding="utf-8")

    report = engine.lint_wiki(db_path=temp_db)
    assert any(l["from"] == "valid.md" and l["to"] == "missing.md" for l in report["broken_markdown_links"])

def test_broken_wikilink(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    content = "---\nentity_id: 1\nentity_type: konzept\ncanonical_name: A\nsource_count: 0\nupdated: '2'\n---\n[[missing|Missing Page]]"
    (wiki_dir / "valid.md").write_text(content, encoding="utf-8")

    report = engine.lint_wiki(db_path=temp_db)
    assert any(l["from"] == "valid.md" and l["to"] == "missing.md" for l in report["broken_wikilinks"])

def test_orphan_page(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    fm = "---\nentity_id: 1\nentity_type: konzept\ncanonical_name: A\nsource_count: 0\nupdated: '2'\n---\n"
    (wiki_dir / "orphan.md").write_text(fm + "# Orphan\n", encoding="utf-8")
    (wiki_dir / "other.md").write_text(fm + "No links here", encoding="utf-8")

    report = engine.lint_wiki(db_path=temp_db)
    assert "orphan.md" in report["orphan_pages"]

def test_duplicate_entity_id(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    fm = "---\nentity_id: dup\nentity_type: konzept\ncanonical_name: A\nsource_count: 0\nupdated: '2'\n---\n"
    (wiki_dir / "file1.md").write_text(fm, encoding="utf-8")
    (wiki_dir / "file2.md").write_text(fm, encoding="utf-8")

    report = engine.lint_wiki(db_path=temp_db)
    assert "dup" in report["duplicate_entity_ids"]
    assert len(report["duplicate_entity_ids"]["dup"]) == 2

def test_duplicate_slugs(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    fm = "---\nentity_id: {}\nentity_type: konzept\ncanonical_name: A\nsource_count: 0\nupdated: '2'\n---\n"

    d1 = wiki_dir / "dir1"
    d1.mkdir()
    d2 = wiki_dir / "dir2"
    d2.mkdir()

    (d1 / "same.md").write_text(fm.format("1"), encoding="utf-8")
    (d2 / "same.md").write_text(fm.format("2"), encoding="utf-8")

    report = engine.lint_wiki(db_path=temp_db)
    assert "same" in report["duplicate_slugs"]
    assert len(report["duplicate_slugs"]["same"]) == 2

def test_invalid_yaml(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    invalid_fm = "---\nentity_id: 1\n  invalid_indent: true\n---\n# Test"
    (wiki_dir / "invalid.md").write_text(invalid_fm, encoding="utf-8")

    report = engine.lint_wiki(db_path=temp_db)
    assert "invalid.md" in report["invalid_frontmatters"]

def test_missing_required_fields(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    fm = "---\nentity_id: 1\n---\n"
    (wiki_dir / "missing.md").write_text(fm, encoding="utf-8")

    report = engine.lint_wiki(db_path=temp_db)
    assert "missing.md" in report["invalid_frontmatters"]

def test_legacy_warning(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    (wiki_dir / "vitali_persona_und_stil.md").write_text("# Persona\n", encoding="utf-8")

    report = engine.lint_wiki(db_path=temp_db)
    assert "vitali_persona_und_stil.md" in report["legacy_warnings"]
    assert "vitali_persona_und_stil.md" not in report["invalid_frontmatters"]

def test_missing_sources(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    fm = {
        "entity_id": "sup1",
        "entity_type": "supplier",
        "canonical_name": "Supplier 1",
        "source_count": 2,
        "updated": "2023-10-01",
        "article_categories": ["food"],
        "skr03_accounts": ["3400"]
    }
    content = f"---\n{yaml.dump(fm)}---\n"
    content += "- `123` | 2023 | 10 EUR | link\n" # Exists in DB
    content += "- `999` | 2023 | 10 EUR | link\n" # Missing in DB
    content += "- `DUBLITTE_MD5_NO_SAVE` | 2023 | 10 EUR | link\n"

    (wiki_dir / "sup.md").write_text(content, encoding="utf-8")

    report = engine.lint_wiki(db_path=temp_db)

    missing = [s for s in report["missing_sources"] if s["source_id"] == "999" and s["status"] == "MISSING_SOURCE"]
    non_file = [s for s in report["missing_sources"] if s["source_id"] == "DUBLITTE_MD5_NO_SAVE" and s["status"] == "NON_FILE_SOURCE"]

    assert len(missing) == 1
    assert len(non_file) == 1
    assert not any(s["source_id"] == "123" for s in report["missing_sources"])

def test_db_unavailable(temp_wiki, tmp_path):
    engine, wiki_dir = temp_wiki
    fm = {
        "entity_id": "sup1",
        "entity_type": "supplier",
        "canonical_name": "Supplier 1",
        "source_count": 1,
        "updated": "2023-10-01",
        "article_categories": ["food"],
        "skr03_accounts": ["3400"]
    }
    content = f"---\n{yaml.dump(fm)}---\n- `999` | 2023 | 10 EUR | link\n"
    (wiki_dir / "sup.md").write_text(content, encoding="utf-8")

    # Missing DB
    missing_db = tmp_path / "does_not_exist.db"
    report = engine.lint_wiki(db_path=missing_db)

    unavail = [s for s in report["missing_sources"] if s["source_id"] == "999" and "SOURCE_DATABASE_UNAVAILABLE" in s["status"]]
    assert len(unavail) == 1

def test_missing_article_types_and_repair(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    fm = {
        "entity_id": "sup1",
        "entity_type": "supplier",
        "canonical_name": "Supplier 1",
        "source_count": 0,
        "updated": "2023-10-01",
        "article_categories": ["Fleisch", "Wein"],
        "skr03_accounts": ["3400"]
    }
    content = f"---\n{yaml.dump(fm)}---\n[[article_category_Käse]]\n"
    (wiki_dir / "sup.md").write_text(content, encoding="utf-8")

    # 1. Normal lint: detects but doesn't create
    report1 = engine.lint_wiki(db_path=temp_db, repair=False)
    assert set(report1["missing_article_categories"]) == {"Fleisch", "Wein", "Käse"}
    assert len(report1["repaired_categories"]) == 0
    assert not (wiki_dir / "entities" / "categories" / "article_category_fleisch.md").exists()

    # 2. Repair lint: creates files deterministically
    report2 = engine.lint_wiki(db_path=temp_db, repair=True)
    assert "article_category_fleisch" in report2["repaired_categories"]
    assert "article_category_k-se" in report2["repaired_categories"] or "article_category_kse" in report2["repaired_categories"] or "article_category_k-se" in [c.lower() for c in report2["repaired_categories"]]

    cat_dir = wiki_dir / "entities" / "categories"
    assert (cat_dir / "article_category_fleisch.md").exists()

    # Check deterministic content
    f_content = (cat_dir / "article_category_fleisch.md").read_text(encoding="utf-8")
    assert "entity_type: article_category" in f_content
    assert "canonical_name: \"Fleisch\"" in f_content
    assert "[[sup]]" in f_content # Relation mapped to the supplier slug

    # 3. Idempotent repair
    report3 = engine.lint_wiki(db_path=temp_db, repair=True)
    assert len(report3["repaired_categories"]) == 0 # no files changed

def test_reports_written(temp_wiki, temp_db, tmp_path):
    engine, wiki_dir = temp_wiki
    fm = "---\nentity_id: 1\nentity_type: konzept\ncanonical_name: A\nsource_count: 0\nupdated: '2'\n---\n"
    (wiki_dir / "valid.md").write_text(fm, encoding="utf-8")

    output_dir = tmp_path / "reports"
    engine.lint_wiki(output_dir=output_dir, db_path=temp_db)

    assert (output_dir / "wiki_lint_report.json").exists()
    assert (output_dir / "wiki_lint_report.md").exists()

    j = json.loads((output_dir / "wiki_lint_report.json").read_text(encoding="utf-8"))
    assert j["total_pages"] == 1


def test_lint_does_not_mutate_wiki(temp_wiki, temp_db, tmp_path):
    engine, wiki_dir = temp_wiki
    page = wiki_dir / "valid.md"
    page.write_text("---\nentity_id: 1\nentity_type: konzept\ncanonical_name: A\nsource_count: 0\nupdated: '2'\n---\n", encoding="utf-8")
    before = {p.relative_to(wiki_dir): p.read_bytes() for p in wiki_dir.rglob("*") if p.is_file()}

    engine.lint_wiki(output_dir=tmp_path / "reports", db_path=temp_db)

    after = {p.relative_to(wiki_dir): p.read_bytes() for p in wiki_dir.rglob("*") if p.is_file()}
    assert after == before


def test_nested_markdown_link_is_resolved_relative_to_source(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    nested = wiki_dir / "entities" / "suppliers"
    nested.mkdir(parents=True)
    fm = "---\nentity_id: {}\nentity_type: konzept\ncanonical_name: A\nsource_count: 0\nupdated: '2'\n---\n"
    (nested / "a.md").write_text(fm.format("a") + "[B](../categories/b.md)\n", encoding="utf-8")
    categories = wiki_dir / "entities" / "categories"
    categories.mkdir()
    (categories / "b.md").write_text(fm.format("b"), encoding="utf-8")

    report = engine.lint_wiki(db_path=temp_db)

    assert report["broken_markdown_links"] == []
    assert "entities/categories/b.md" not in report["orphan_pages"]


def test_existing_category_uses_normalized_slug(temp_wiki, temp_db):
    engine, wiki_dir = temp_wiki
    suppliers = wiki_dir / "entities" / "suppliers"
    categories = wiki_dir / "entities" / "categories"
    suppliers.mkdir(parents=True)
    categories.mkdir(parents=True)
    supplier_fm = {
        "entity_id": "sup1", "entity_type": "supplier", "canonical_name": "S",
        "source_count": 0, "updated": "2026-01-01", "article_categories": ["Käse"],
        "skr03_accounts": [],
    }
    (suppliers / "s.md").write_text(f"---\n{yaml.safe_dump(supplier_fm)}---\n", encoding="utf-8")
    (categories / "article_category_k-se.md").write_text(
        "---\nentity_id: cat\nentity_type: article_category\ncanonical_name: Käse\nsource_count: 0\nupdated: '2'\n---\n",
        encoding="utf-8",
    )

    report = engine.lint_wiki(db_path=temp_db)

    assert report["missing_article_categories"] == []
