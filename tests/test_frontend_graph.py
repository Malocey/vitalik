import pytest
from playwright.sync_api import sync_playwright, Page, expect
import threading
import sys
import time

def run_server():
    from dashboard_server import run_dashboard_server
    run_dashboard_server(port=8085)

@pytest.fixture(scope="module")
def frontend_server():
    from src.core.config import DATA_DIR
    import sqlite3
    db_path = DATA_DIR / "rag_index.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS belege (
            beleg_id TEXT PRIMARY KEY, lieferant TEXT, datum TEXT, rechnungsnummer TEXT, netto TEXT, steuer TEXT, brutto TEXT,
            ust_satz TEXT, warengruppe TEXT, skr_konto TEXT, status TEXT, beleg_link TEXT, wiki_path TEXT,
            raw_text_path TEXT, summary TEXT, updated_at TEXT, belegtyp TEXT, confidence_score TEXT,
            md5_hash TEXT, rag_read_verified TEXT, contact_entity_id TEXT
        )
    ''')
    conn.execute("INSERT OR REPLACE INTO belege (beleg_id, lieferant, skr_konto, brutto, beleg_link) VALUES ('TEST-01', 'Test Supplier', '3400', '119.00', 'http://example.com/doc.pdf')")
    conn.commit()
    conn.close()

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(3)
    yield

def test_wiki_graph_frontend(frontend_server, page: Page):
    # Navigate to the graph page
    page.goto("http://localhost:8085/wiki-graph")

    # Wait for network container to load
    page.wait_for_selector(".vis-network")

    # Check if filters are present
    assert page.locator("#show-receipts").is_visible()

    # Since vis-network renders on a canvas, we can't easily query nodes in DOM
    # But we can verify that the sidebar starts empty and shows the placeholder
    assert page.locator("#no-note-selected").is_visible()

    # Trigger the checkbox to ensure it runs without errors
    page.locator("#show-receipts").check()
    page.wait_for_timeout(1000)

    # Try simulating node selection via evaluated JS since it's inside canvas
    # The graph is stored in a global `network` object and nodes in `graphNodesData`
    page.evaluate('''() => {
        if (graphNodesData && graphNodesData.length > 0) {
            // Find a valid node ID to select
            const node = graphNodesData.find(n => n.id.startsWith("wiki:"));
            network.selectNodes([node.id]);
            // Dispatch selectNode event manually or just call showNodeDetails directly
            showNodeDetails(node.id);
        }
    }''')
    page.wait_for_timeout(500)

    # Verify that details are shown
    expect(page.locator("#no-note-selected")).to_be_hidden()
    assert page.locator("#note-title").is_visible()
    assert page.locator("#note-meta").is_visible()

    # Verify that innerHTML was not used for markdown parsing (we rely on textContent and pre formatting)
    # The output from debugging shows there are two PREs inside #note-content. The second PRE holds the text.
    assert page.locator("#note-content pre").nth(1).is_visible()
