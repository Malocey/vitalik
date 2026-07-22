import pytest
import sqlite3
import json
from pathlib import Path
from src.core.reconcile_document_entities import reconcile_entities, extract_strong_ids_from_text

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "rag_index.db"
    conn = sqlite3.connect(db_path)

    # Init minimal schema for testing
    conn.executescript("""
        CREATE TABLE contact_entities (
            entity_id TEXT PRIMARY KEY, role TEXT, canonical_name TEXT, normalized_name TEXT,
            tax_id TEXT, iban TEXT, email TEXT, postal_code TEXT, city TEXT, sevdesk_id TEXT
        );
        CREATE TABLE contact_aliases (
            role TEXT, normalized_alias TEXT, entity_id TEXT
        );
        CREATE TABLE belege (
            beleg_id TEXT PRIMARY KEY, lieferant TEXT, beleg_link TEXT, raw_text_path TEXT,
            sevdesk_kunden_nr TEXT, contact_entity_id TEXT
        );
        CREATE VIRTUAL TABLE belege_ocr_fts USING fts5(
            beleg_id UNINDEXED, rohtext, tokenize='unicode61'
        );
    """)

    # Insert contact entities
    conn.executescript("""
        INSERT INTO contact_entities (entity_id, role, canonical_name, normalized_name, tax_id, iban, sevdesk_id)
        VALUES
        ('ent_frische', 'supplier', 'Frischeparadies', 'frischeparadies', 'DE123456789', 'DE999999', 'SEV_1'),
        ('ent_jens', 'supplier', 'Jensmann', 'jensmann', 'DE987654321', 'DE888888', 'SEV_2'),
        ('ent_trans', 'supplier', 'Transgourmet', 'transgourmet', 'DE111111111', 'DE777777', 'SEV_3');

        INSERT INTO contact_aliases (role, normalized_alias, entity_id)
        VALUES
        ('supplier', 'frischeparadies', 'ent_frische'),
        ('supplier', 'jensmann', 'ent_jens'),
        ('supplier', 'transgourmet', 'ent_trans');
    """)

    # Insert 5 known conflict cases
    conn.executescript("""
        INSERT INTO belege (beleg_id, lieferant, beleg_link) VALUES
        ('b1', 'Frischeparadies', 'rechnung_jensmann.pdf'),
        ('b2', 'Frischeparadies', 'transgourmet_2023.pdf'),
        ('b3', 'Frischeparadies', 'rechnung.pdf'),
        ('b4', 'Frischeparadies', 'rg.pdf'),
        ('b5', 'Frischeparadies', 'jensmann_rg.pdf');

        INSERT INTO belege_ocr_fts (beleg_id, rohtext) VALUES
        ('b3', '... jensmann ...'),
        ('b4', '... transgourmet ...');
    """)

    # Insert valid idempotent update cases
    conn.executescript("""
        INSERT INTO belege (beleg_id, lieferant, beleg_link, sevdesk_kunden_nr, contact_entity_id) VALUES
        ('b_safe_1', 'Frischeparadies', 'rg.pdf', 'SEV_1', NULL),
        ('b_safe_2', 'Jensmann', 'rg.pdf', 'SEV_2', 'ent_jens');

        INSERT INTO belege_ocr_fts (beleg_id, rohtext) VALUES
        ('b_safe_1', '... DE123456789 ...');
    """)

    conn.commit()
    conn.close()

    return db_path

def test_frischeparadies_conflict_cases(temp_db, tmp_path):
    report_dir = tmp_path / "reports"
    reconcile_entities(str(temp_db), str(report_dir), apply=False)

    summary_file = report_dir / "summary.json"
    conflicts_file = report_dir / "conflicts.csv"

    assert summary_file.exists()
    assert conflicts_file.exists()

    with open(summary_file) as f:
        summary = json.load(f)

    assert summary["conflicts"] == 5
    assert summary["updated"] == 1  # b_safe_1 gets updated

    with open(conflicts_file) as f:
        content = f.read()
        assert "b1" in content
        assert "b2" in content
        assert "b3" in content
        assert "b4" in content
        assert "b5" in content

def test_idempotent_updates(temp_db, tmp_path):
    report_dir = tmp_path / "reports"
    reconcile_entities(str(temp_db), str(report_dir), apply=True)

    # Second run should produce 0 updates
    report_dir_2 = tmp_path / "reports_2"
    reconcile_entities(str(temp_db), str(report_dir_2), apply=True)

    with open(report_dir_2 / "summary.json") as f:
        summary = json.load(f)

    assert summary["updated"] == 0

def test_extract_strong_ids():
    text = "Hier ist meine USt-ID: DE123456789 und IBAN: DE99887766554433221100. E-Mail: test@example.com"
    ids = extract_strong_ids_from_text(text)
    assert "DE123456789" in ids["ust_id"]
    assert "DE99887766554433221100" in ids["iban"]
    assert "test@example.com" in ids["email"]
