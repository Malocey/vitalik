import tempfile
from pathlib import Path
from src.core.matching_engine import MatchingEngine
from src.core.price_monitor import PriceMonitor


def test_matching_engine():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_db = Path(f.name)
    try:
        engine = MatchingEngine(db_path=tmp_db)

        invoice = {
            "beleg_id": "RE-2026-001",
            "lieferant": "Fleischerei Metro",
            "brutto": 250.00
        }
        delivery_note = {
            "beleg_id": "LS-2026-001",
            "lieferant": "Fleischerei Metro",
            "brutto": 250.00
        }

        res = engine.match_invoice_with_delivery_note(invoice, delivery_note)
        assert res["match_status"] == "MATCHED"
        assert res["confidence_score"] == 0.95
        assert len(res["discrepancies"]) == 0

        all_matches = engine.get_all_matches()
        assert len(all_matches) == 1
        assert all_matches[0]["invoice_id"] == "RE-2026-001"
    finally:
        if tmp_db.exists():
            try:
                tmp_db.unlink()
            except OSError:
                pass


def test_matching_engine_discrepancy():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_db = Path(f.name)
    try:
        engine = MatchingEngine(db_path=tmp_db)

        invoice = {
            "beleg_id": "RE-2026-002",
            "lieferant": "Fleischerei Metro",
            "brutto": 300.00
        }
        delivery_note = {
            "beleg_id": "LS-2026-002",
            "lieferant": "Fleischerei Metro",
            "brutto": 250.00
        }

        res = engine.match_invoice_with_delivery_note(invoice, delivery_note)
        assert res["match_status"] == "DISCREPANCY"
        assert len(res["discrepancies"]) > 0
    finally:
        if tmp_db.exists():
            try:
                tmp_db.unlink()
            except OSError:
                pass


def test_matching_respects_contact_and_date_window(tmp_path):
    engine = MatchingEngine(db_path=tmp_path / "matching.db")
    result = engine.match_invoice_with_delivery_note(
        {"beleg_id": "R1", "lieferant": "Gleich", "contact_entity_id": "A",
         "datum": "2026-07-20", "brutto": 10},
        {"beleg_id": "L1", "lieferant": "Gleich", "contact_entity_id": "B",
         "datum": "2026-05-01", "brutto": 10},
    )
    assert result["match_status"] == "DISCREPANCY"
    assert len(result["discrepancies"]) == 2


def test_price_recording_is_idempotent_per_document(tmp_path):
    monitor = PriceMonitor(db_path=tmp_path / "prices.db")
    monitor.record_price(" Metro ", "Rinderfilet  kg", 12.5, "Kilogramm", "RE-1")
    monitor.record_price("Metro", "Rinderfilet kg", 13.0, "kg", "RE-1")
    trends = monitor.get_price_trends()
    assert len(trends) == 1
    assert trends[0]["data_points"] == 1
    assert trends[0]["latest_price"] == 13.0
def test_price_monitor():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_db = Path(f.name)
    try:
        monitor = PriceMonitor(db_path=tmp_db)

        # Record initial price
        monitor.record_price("Metro", "Rinderfilet kg", 12.50, "kg", "RE-001")
        # Record updated price
        monitor.record_price("Metro", "Rinderfilet kg", 13.80, "kg", "RE-002")

        trends = monitor.get_price_trends()
        assert len(trends) == 1
        item = trends[0]
        assert item["supplier_name"] == "Metro"
        assert item["item_name"] == "Rinderfilet kg"
        assert item["oldest_price"] == 12.50
        assert item["latest_price"] == 13.80
        assert item["change_pct"] == 10.4  # +10.4% increase
        assert item["status"] == "PREISERHOEHUNG_WARNUNG"
    finally:
        if tmp_db.exists():
            try:
                tmp_db.unlink()
            except OSError:
                pass
