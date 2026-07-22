import tempfile
from pathlib import Path
from src.core.email_decision_engine import email_decision_engine
from src.core.email_draft_generator import EmailDraftGenerator
from src.core.validation_shield import ValidationShield


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
        assert "weder die sachliche Prüfung noch eine Zahlungsfreigabe" in draft["generated_draft"]
        
        pending = generator.get_pending_drafts()
        assert len(pending) == 1
        assert pending[0]["supplier_name"] == "Metro Grosshandel"

        repeated = generator.generate_draft(email_data, classification)
        assert repeated["draft_id"] == draft["draft_id"]
        assert len(generator.get_pending_drafts()) == 1
    finally:
        if tmp_db.exists():
            try:
                tmp_db.unlink()
            except OSError:
                pass


def test_non_bookable_email_never_passes_without_amount():
    shield = ValidationShield()
    passed, _, receipt = shield.validate_document({
        "belegtyp": "Quittung / Zahlungsbestaetigung", "brutto": 0.0,
        "raw_text": "Quittung", "confidence_score": 1.0,
    })
    assert not passed
    assert receipt["validation_status"] == "MANUAL_REVIEW_NEEDED"

    passed, _, price_notice = shield.validate_document({
        "belegtyp": "Preiserhöhungs-Mitteilung", "brutto": 0.0,
        "raw_text": "Preisanpassung", "confidence_score": 1.0,
    })
    assert not passed
    assert price_notice["validation_status"] == "EMAIL_INFO"
