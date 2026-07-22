import tempfile
import pytest
from pathlib import Path
from src.parser.multi_format_engine import multi_format_engine, MultiFormatEngine

def test_supported_extensions():
    engine = MultiFormatEngine()
    assert engine.is_supported(Path("invoice.pdf")) is True
    assert engine.is_supported(Path("offer.docx")) is True
    assert engine.is_supported(Path("price_list.xlsx")) is True
    assert engine.is_supported(Path("data.csv")) is True
    assert engine.is_supported(Path("mail.eml")) is True
    assert engine.is_supported(Path("mail.msg")) is False
    assert engine.is_supported(Path("legacy.doc")) is False
    assert engine.is_supported(Path("legacy.xls")) is False
    assert engine.is_supported(Path("note.txt")) is True
    assert engine.is_supported(Path("archive.zip")) is False

def test_extract_plain_text():
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
        f.write("Lieferant: Metro Grossmarkt\nDatum: 2026-07-20\nBrutto: 150.00 EUR")
        tmp_path = Path(f.name)
    try:
        res = multi_format_engine.extract_document(tmp_path)
        assert len(res) == 1
        assert "Metro Grossmarkt" in res[0]["full_text"]
        assert res[0]["ocr_status"] == "PLAIN_TEXT"
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

def test_extract_csv():
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False, encoding="utf-8") as f:
        f.write("Lieferant,Datum,Brutto\nEdeka,2026-06-15,85.00\nMetro,2026-05-14,142.50")
        tmp_path = Path(f.name)
    try:
        res = multi_format_engine.extract_document(tmp_path)
        assert len(res) == 1
        assert "Edeka" in res[0]["full_text"]
        assert "| Edeka | 2026-06-15 | 85.00 |" in res[0]["full_text"]
        assert res[0]["ocr_status"] == "CSV"
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

def test_extract_eml():
    eml_content = (
        "From: metro@groshandel.de\n"
        "To: info@vg-delikatessen.de\n"
        "Subject: Ihre Monatsrechnung Juli 2026\n"
        "Date: Wed, 22 Jul 2026 10:00:00 +0200\n"
        "Content-Type: text/plain; charset=utf-8\n\n"
        "Sehr geehrter Herr Vitali,\n"
        "anbei erhalten Sie Ihre Monatsrechnung über 450.00 EUR.\n"
        "Lieferant: Metro Grosshandel AG\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".eml", mode="w", delete=False, encoding="utf-8") as f:
        f.write(eml_content)
        tmp_path = Path(f.name)
    try:
        res = multi_format_engine.extract_document(tmp_path)
        assert len(res) == 1
        assert "Metro Grosshandel AG" in res[0]["full_text"]
        assert "Monatsrechnung Juli 2026" in res[0]["full_text"]
        assert res[0]["ocr_status"] == "EMAIL_EML"
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def test_image_uses_quality_ocr(monkeypatch, tmp_path):
    from src.parser.ocr_engine import ocr_engine
    image = tmp_path / "receipt.png"
    image.write_bytes(b"not-a-real-image")
    monkeypatch.setattr(ocr_engine, "extract_with_quality", lambda path: {
        "text": "Rechnung 100 EUR", "confidence": 0.91, "status": "OCR_OK"
    })
    result = MultiFormatEngine().extract_document(image)
    assert result[0]["full_text"] == "Rechnung 100 EUR"
    assert result[0]["ocr_confidence"] == 0.91


def test_rejects_oversized_input(tmp_path):
    path = tmp_path / "large.txt"
    path.write_text("12345", encoding="utf-8")
    engine = MultiFormatEngine()
    engine.MAX_FILE_BYTES = 4
    with pytest.raises(ValueError, match="überschreitet"):
        engine.extract_document(path)
