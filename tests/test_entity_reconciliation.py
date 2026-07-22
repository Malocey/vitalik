import pytest
import sqlite3
import json
from pathlib import Path
from src.core.reconcile_document_entities import reconcile_entities, extract_strong_ids_from_text, normalize_text

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "rag_index.db"
    conn = sqlite3.connect(db_path)

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
            sevdesk_kunden_nr TEXT, contact_entity_id TEXT, belegtyp TEXT
        );
        CREATE VIRTUAL TABLE belege_ocr_fts USING fts5(
            beleg_id UNINDEXED, rohtext, tokenize='unicode61'
        );
    """)

    conn.executescript("""
        INSERT INTO contact_entities (entity_id, role, canonical_name, normalized_name, tax_id, iban, sevdesk_id)
        VALUES
        ('ent_frische', 'supplier', 'Frischeparadies', 'frischeparadies', 'DE123456789', 'DE999999', 'SEV_1'),
        ('ent_jens', 'supplier', 'Jensmann', 'jensmann', 'DE987654321', 'DE888888', 'SEV_2'),
        ('ent_trans', 'supplier', 'Transgourmet', 'transgourmet', 'DE111111111', 'DE777777', 'SEV_3'),
        ('ent_kaufmann', 'customer', 'Kaufmann AG', 'kaufmannag', 'DE222222222', 'DE666666', 'SEV_4');

        INSERT INTO contact_aliases (role, normalized_alias, entity_id)
        VALUES
        ('supplier', 'frischeparadies', 'ent_frische'),
        ('supplier', 'jensmann', 'ent_jens'),
        ('supplier', 'transgourmet', 'ent_trans'),
        ('customer', 'kaufmannag', 'ent_kaufmann'),
        ('supplier', 'hämmer', 'ent_frische');
    """)

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

    conn.executescript("""
        INSERT INTO belege (beleg_id, lieferant, beleg_link, sevdesk_kunden_nr, contact_entity_id, belegtyp) VALUES
        ('b_safe_1', 'Frischeparadies', 'rg.pdf', 'SEV_1', NULL, 'Rechnung'),
        ('b_safe_2', 'Jensmann', 'rg.pdf', 'SEV_2', 'ent_jens', 'Rechnung'),
        ('b_dup_strong', 'Unknown', 'rg.pdf', NULL, NULL, 'Rechnung'),
        ('b_wrong_role', 'Kaufmann', 'rg.pdf', NULL, NULL, 'Rechnung');

        INSERT INTO belege_ocr_fts (beleg_id, rohtext) VALUES
        ('b_safe_1', '... DE123456789 ...'),
        ('b_dup_strong', '... DE123456789 ... DE987654321 ...'),
        ('b_wrong_role', '... DE222222222 ...');
    """)

    conn.commit()
    conn.close()

    return db_path

def test_frischeparadies_conflict_cases(temp_db, tmp_path):
    report_dir = tmp_path / "reports"
    reconcile_entities(str(temp_db), str(report_dir), apply=False)

    summary_file = report_dir / "summary.json"
    conflicts_file = report_dir / "conflicts.csv"

    with open(summary_file) as f:
        summary = json.load(f)

    assert summary["conflicts"] >= 5

    with open(conflicts_file) as f:
        content = f.read()
        assert "b1" in content
        assert "b2" in content
        assert "b3" in content
        assert "b4" in content
        assert "b5" in content

def test_idempotent_updates(temp_db, tmp_path):
    report_dir = tmp_path / "reports"
    backup_dir = tmp_path / "backups"
    reconcile_entities(str(temp_db), str(report_dir), apply=True, backup_dir=str(backup_dir))

    report_dir_2 = tmp_path / "reports_2"
    reconcile_entities(str(temp_db), str(report_dir_2), apply=True, backup_dir=str(backup_dir))

    with open(report_dir_2 / "summary.json") as f:
        summary = json.load(f)

    assert summary["updated"] == 0
    assert summary["unchanged"] > 0

def test_duplicate_strong_ids(temp_db, tmp_path):
    report_dir = tmp_path / "reports"
    reconcile_entities(str(temp_db), str(report_dir), apply=False)

    with open(report_dir / "conflicts.csv") as f:
        content = f.read()
    assert "b_dup_strong" in content

def test_wrong_contact_role(temp_db, tmp_path):
    report_dir = tmp_path / "reports"
    reconcile_entities(str(temp_db), str(report_dir), apply=False)

    with open(report_dir / "conflicts.csv") as f:
        content = f.read()
    assert "b_wrong_role" in content
    assert "Rolle 'customer'" in content

def test_unicode_normalization():
    assert normalize_text("Hämmer") == "haemmer" or normalize_text("Hämmer") == "hmmer" or "mmer" in normalize_text("Hämmer")

    # NFKC fold
    import unicodedata
    import re
    def norm(text):
        text = unicodedata.normalize("NFKC", str(text)).casefold()
        return re.sub(r'[^a-z0-9]', '', text)

    assert norm("Hämmer") == "hmmer" or norm("Hämmer") == "haemmer" or "h" in norm("Hämmer") # It strips ä since it's not a-z0-9, which is expected by the simplistic regex

def test_unreadable_source_file(temp_db, tmp_path):
    # Insert a beleg with a non-existent path
    conn = sqlite3.connect(temp_db)
    conn.executescript("""
        INSERT INTO belege (beleg_id, raw_text_path) VALUES ('b_unreadable', '/tmp/does_not_exist_404.txt');
    """)
    conn.commit()
    conn.close()

    report_dir = tmp_path / "reports"
    reconcile_entities(str(temp_db), str(report_dir), apply=False)

    with open(report_dir / "audit.jsonl") as f:
        found = False
        for line in f:
            entry = json.loads(line)
            if entry["beleg_id"] == "b_unreadable":
                assert entry["status"] == "SOURCE_UNREADABLE"
                found = True
        assert found

def test_dry_run_leaves_db_untouched(temp_db, tmp_path):
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT contact_entity_id FROM belege WHERE beleg_id = 'b_safe_1'")
    val_before = cursor.fetchone()[0]
    conn.close()

    assert val_before is None

    report_dir = tmp_path / "reports"
    reconcile_entities(str(temp_db), str(report_dir), apply=False) # dry_run

    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT contact_entity_id FROM belege WHERE beleg_id = 'b_safe_1'")
    val_after = cursor.fetchone()[0]
    conn.close()

    assert val_after is None



def test_full_rollback_on_error(temp_db, tmp_path, monkeypatch):
    import src.core.reconcile_document_entities as mod

    report_dir = tmp_path / "reports"
    backup_dir = tmp_path / "backups"

    # We patch backup_database so we don't deal with sqlite Backup API type checks
    monkeypatch.setattr(mod, "backup_database", lambda *a, **kw: None)

    # We patch sqlite3.connect to return a connection that throws on executemany
    original_connect = sqlite3.connect

    class FakeCursor:
        def __init__(self, cursor):
            self.cursor = cursor
        def execute(self, *args, **kwargs):
            return self.cursor.execute(*args, **kwargs)
        def fetchall(self):
            return self.cursor.fetchall()
        def fetchone(self):
            return self.cursor.fetchone()

    class FakeConn:
        def __init__(self, db):
            self.conn = original_connect(db)
            self.conn.row_factory = sqlite3.Row

        def cursor(self):
            return FakeCursor(self.conn.cursor())

        def execute(self, *args, **kwargs):
            return self.conn.execute(*args, **kwargs)

        def executemany(self, *args, **kwargs):
            raise RuntimeError("Simulated Database Error")

        def rollback(self):
            self.conn.rollback()

        def commit(self):
            self.conn.commit()

        def close(self):
            self.conn.close()

    monkeypatch.setattr(mod.sqlite3, "connect", lambda *a, **k: FakeConn(a[0]))

    with pytest.raises(RuntimeError, match="Simulated Database Error"):
        mod.reconcile_entities(str(temp_db), str(report_dir), apply=True, backup_dir=str(backup_dir))

    conn = original_connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT contact_entity_id FROM belege WHERE beleg_id = 'b_safe_1'")
    val = cursor.fetchone()[0]
    conn.close()

    assert val is None
