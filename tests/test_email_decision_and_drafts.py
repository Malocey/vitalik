import tempfile
from pathlib import Path
from src.core.email_decision_engine import email_decision_engine
from src.core.email_draft_generator import EmailDraftGenerator


def test_email_decision_classification():
    email_data = {
        "from": "Metro Grosshandel <metro@groshandel.de>",
        "subject": "Wichtige Preisanpassung Juli 2026",
        "body": "Sehr geehrter Kunde, aufgrund steigender Energiekosten müssen wir eine Preiserhöhung ankündigen."
    }
    
    res = email_decision_engine.classify_email(email_data)
    assert res["intent"] == "PREIS_ERHOEHUNG"
    assert "Preiserhöhung" in res["suggested_action"]
    assert "Metro" in res["supplier_name"]


def test_email_draft_generation():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_db = Path(f.name)
        
    try:
        generator = EmailDraftGenerator(db_path=tmp_db)
        
        email_data = {
            "from": "Metro Grosshandel <metro@groshandel.de>",
            "subject": "Monatsrechnung Juli 2026",
            "body": "Anbei erhalten Sie Ihre Monatsrechnung über 450,00 EUR."
        }
        
        classification = {
            "supplier_name": "Metro Grosshandel",
            "sender_email": "metro@groshandel.de",
            "subject": "Monatsrechnung Juli 2026",
            "intent": "RECHNUNG_INVOICE",
            "suggested_action": "Rechnungseingang bestätigen"
        }
        
        draft = generator.generate_draft(email_data, classification)
        assert draft["intent"] == "RECHNUNG_INVOICE"
        assert "Servus Metro Grosshandel-Team" in draft["generated_draft"]
        assert "Rechnung wurde in unserem System erfasst" in draft["generated_draft"]
        
        pending = generator.get_pending_drafts()
        assert len(pending) == 1
        assert pending[0]["supplier_name"] == "Metro Grosshandel"
    finally:
        if tmp_db.exists():
            try:
                tmp_db.unlink()
            except OSError:
                pass
