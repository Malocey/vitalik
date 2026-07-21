"""Integrationstest für die sevDesk-gestützte Belegzuordnung."""

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.rag_engine import rag_engine
from src.core.validation_shield import validation_shield
from src.parser.analyzer import document_analyzer


def test_sevdesk_assignment() -> None:
    with sqlite3.connect(rag_engine.db_path) as db:
        supplier = db.execute("""
            SELECT kunden_nr, COALESCE(NULLIF(organisation, ''), trim(vorname || ' ' || nachname))
            FROM sevdesk_contacts WHERE lower(kategorie) = 'lieferant'
            LIMIT 1
        """).fetchone()
        article = db.execute("""
            SELECT artikelnummer, name FROM sevdesk_articles
            WHERE umsatzsteuer = 7.0 AND length(name) >= 5 LIMIT 1
        """).fetchone()

    assert supplier and article, "Für den Zuordnungstest fehlen sevDesk-Stammdaten."
    text = f"Rechnung von {supplier[1]}\nArtikel: {article[1]}\nGesamt 107,00 EUR"
    assignment = rag_engine.match_sevdesk_assignment(text)
    assert assignment["supplier"]["kunden_nr"] == supplier[0]
    assert any(item["artikelnummer"] == article[0] for item in assignment["articles"])

    document = document_analyzer._apply_sevdesk_assignment({
        "lieferant": "UNKNOWN", "datum": "2026-07-21",
        "netto": 100.0, "steuer": 7.0, "brutto": 107.0,
        "confidence_score": 0.99, "warengruppe": "Unbekannt",
    }, assignment)
    passed, _, enriched = validation_shield.validate_document(document)
    assert passed
    assert enriched["lieferant"] == supplier[1]
    assert enriched["skr03_konto"] == "3400"
    assert enriched["steuersatz_prozent"] == 7.0
    assert enriched["lieferant_match_source"] == "sevdesk_contacts"
    assert enriched["steuer_match_source"] == "sevdesk_articles"
    print("sevDesk-Zuordnungstest erfolgreich")


if __name__ == "__main__":
    test_sevdesk_assignment()
