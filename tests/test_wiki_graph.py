import pytest
import sqlite3
import os
from pathlib import Path
from src.wiki.wiki_engine import KarpathyLLMWikiEngine

@pytest.fixture
def temp_wiki(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()

    # Create standard files
    (wiki_dir / "index.md").write_text("# Index")
    (wiki_dir / "log.md").write_text("# Log")

    # Create an archive file (should be excluded)
    archive_dir = wiki_dir / "archive"
    archive_dir.mkdir()
    (archive_dir / "old_file.md").write_text("# Old")

    # Create two files with same name in different subfolders
    sub1 = wiki_dir / "entities" / "suppliers"
    sub1.mkdir(parents=True)
    (sub1 / "commerzbank.md").write_text(
        "---\n"
        "entity_type: supplier\n"
        "entity_id: supplier_cb\n"
        "---\n"
        "# Commerzbank\n"
        "- `beleg_1` | 2024-01-01 | 10 EUR | [Quelle]()\n"
        "[[article_category_bank]]\n"
    )

    sub2 = wiki_dir / "entities" / "contacts"
    sub2.mkdir(parents=True)
    (sub2 / "commerzbank.md").write_text(
        "---\n"
        "entity_type: contact\n"
        "entity_id: contact_cb\n"
        "summary: Bankkontakt\n"
        "---\n"
        "# Commerzbank Kontakt\n"
    )

    # Legacy page without frontmatter
    (wiki_dir / "legacy.md").write_text(
        "# Legacy Page\n"
        "*Kategorie: alt*\n\n"
        "Hier steht Text.\n"
        "- **Ort/Land:** Almaty, Kasachstan\n"
        "- **sevDesk-Kontakt-ID:** 1000\n"
        "## Verdichtetes Wissen\n"
        "Dieser Text ist die Legacy Kurzfassung.\n"
    )

    # Ambiguous link page
    (wiki_dir / "hub.md").write_text(
        "# Hub\n"
        "[[commerzbank]]\n"
    )

    return wiki_dir

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "rag_index.db"
    conn = sqlite3.connect(db_path)
    conn.execute('''
        CREATE TABLE belege (
            beleg_id TEXT, lieferant TEXT, datum TEXT, rechnungsnummer TEXT, netto TEXT, steuer TEXT, brutto TEXT,
            ust_satz TEXT, warengruppe TEXT, skr_konto TEXT, status TEXT, beleg_link TEXT, wiki_path TEXT,
            raw_text_path TEXT, summary TEXT, updated_at TEXT, belegtyp TEXT, confidence_score TEXT,
            md5_hash TEXT, rag_read_verified TEXT, contact_entity_id TEXT
        )
    ''')
    conn.execute("INSERT INTO belege (beleg_id, lieferant, skr_konto, brutto) VALUES ('beleg_1', 'Commerzbank', '3400', '119.00')")
    conn.commit()
    conn.close()
    return db_path

def test_wiki_graph_data(temp_wiki, temp_db):
    engine = KarpathyLLMWikiEngine(wiki_dir=temp_wiki)
    data = engine.get_graph_data(db_path=str(temp_db))

    nodes = {n['id']: n for n in data['nodes']}
    edges = data['edges']
    warnings = data['warnings']

    # Check nodes
    assert 'wiki:index' not in nodes
    assert 'wiki:log' not in nodes
    assert 'wiki:archive/old_file' not in nodes

    cb_supplier = 'wiki:entities/suppliers/commerzbank'
    cb_contact = 'wiki:entities/contacts/commerzbank'
    legacy = 'wiki:legacy'

    assert cb_supplier in nodes
    assert cb_contact in nodes
    assert legacy in nodes

    # Check legacy fields extraction
    assert nodes[legacy]['ort_land'] == 'Almaty, Kasachstan'
    assert nodes[legacy]['sevdesk_id'] == '1000'
    assert nodes[legacy]['summary'] == 'Dieser Text ist die Legacy Kurzfassung.'

    # Check ambiguous link warning
    ambig = [w for w in warnings if w['code'] == 'AMBIGUOUS_LINK']
    assert len(ambig) == 1
    assert ambig[0]['target'] == 'commerzbank'
    assert set(ambig[0]['candidates']) == {cb_supplier, cb_contact}

    # Check edges
    has_source_edge = any(e['from'] == cb_supplier and e['to'] == 'receipt:beleg_1' and e['relation'] == 'source_receipt' for e in edges)
    assert has_source_edge

    # Check virtual receipt node
    assert 'receipt:beleg_1' in nodes
    assert nodes['receipt:beleg_1']['virtual'] is True
    assert nodes['receipt:beleg_1']['brutto'] == '119.00'
    assert nodes['receipt:beleg_1']['skr_konto'] == '3400'

    # Check virtual account node
    assert 'account:3400' in nodes
    assert nodes['account:3400']['virtual'] is True
    assert nodes['account:3400']['account_number'] == '3400'

    has_account_edge = any(e['from'] == cb_supplier and e['to'] == 'account:3400' for e in edges) # No edge if derived from receipt unless specified?

def test_missing_db(temp_wiki):
    engine = KarpathyLLMWikiEngine(wiki_dir=temp_wiki)
    data = engine.get_graph_data(db_path="/does/not/exist.db")

    warnings = data['warnings']
    assert any(w['code'] == 'SQLITE_UNAVAILABLE' for w in warnings)

    nodes = {n['id']: n for n in data['nodes']}
    assert 'wiki:entities/suppliers/commerzbank' in nodes
    assert 'receipt:beleg_1' not in nodes
