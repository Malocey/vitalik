#!/usr/bin/env python3
"""
Verifikationstest für die Dubletten-Erkennungs-Engine (MD5 & Metadaten-Matching).
"""

import sys
import logging
from pathlib import Path
from unittest.mock import patch

# Windows UTF-8 Terminal Support
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Projektpfad auflösen
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from src.core.config import MOCK_DRIVE_DIR
from pipeline import ArchivePipeline
from src.parser.pdf_engine import pdf_engine

# Setup logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TestDuplicates")

def cleanup_files():
    for f in ["test_dup_base.pdf", "test_dup_meta.pdf"]:
        p = Path(f)
        if p.exists():
            p.unlink()

def run_tests():
    logger.info("=== INITIALISIERE DUBLETTEN-VERIFIKATIONSTEST ===")
    
    # 1. Dashboard-Datei aufräumen für saubere Testbedingungen
    root_path = MOCK_DRIVE_DIR / "[ VG_Delikatessen_Zentrale ]"
    dashboard_file = root_path / "📊 VG_Zentral_Dashboard.csv"
    if dashboard_file.exists():
        dashboard_file.unlink()
        logger.info("[Test] Altes Test-Dashboard gelöscht.")
        
    # Auch den Ordner 'DUBLITTEN' säubern
    dub_dir = root_path / "04_Pruefung_Erforderlich" / "DUBLITTEN"
    if dub_dir.exists():
        for f in dub_dir.glob("*.pdf"):
            f.unlink()
        logger.info("[Test] Dubletten-Zielordner gesäubert.")

    # 2. Erstelle zwei PDF-Dateien mit unterschiedlichen MD5s
    from pypdf import PdfWriter
    
    # PDF 1
    w1 = PdfWriter()
    w1.add_blank_page(width=72, height=72)
    pdf1 = Path("test_dup_base.pdf")
    with open(pdf1, "wb") as f:
        w1.write(f)
        
    # PDF 2 (andere Abmessungen -> anderer MD5 Hash)
    w2 = PdfWriter()
    w2.add_blank_page(width=80, height=80)
    pdf2 = Path("test_dup_meta.pdf")
    with open(pdf2, "wb") as f:
        w2.write(f)

    md5_1 = pdf_engine.calculate_md5(pdf1)
    md5_2 = pdf_engine.calculate_md5(pdf2)
    
    logger.info(f"[Test] PDF 1 MD5: {md5_1}")
    logger.info(f"[Test] PDF 2 MD5: {md5_2}")
    assert md5_1 != md5_2, "MD5 Hashes müssen sich unterscheiden!"

    # 3. Pipeline instanziieren
    pipeline = ArchivePipeline()
    
    # --- TEST 1: Erstmaliger Import (Erfolgreich) ---
    logger.info("\n--- TEST 1: Erstmaliger Import ---")
    mock_pages_info_1 = [
        {
            "page_num": 1,
            "text_snippet": "Metro Rechnung. Datum: 2026-05-14. Lieferant: Metro. Brutto: 142.50. USt: 9.32.",
            "full_text": "Rechnung Metro. Lieferant: Metro. Datum: 2026-05-14. Brutto: 142.50. Netto: 133.18. Steuer: 9.32. Seite 1 von 1."
        }
    ]
    
    with patch("src.parser.pdf_engine.pdf_engine.inspect_pdf", return_value=mock_pages_info_1):
        results = pipeline.process_pdf_archive(pdf1)
        
    assert len(results) == 1, "Sollte 1 Ergebnis liefern"
    assert results[0]["passed"] is True, "Sollte erfolgreich validiert sein"
    assert results[0]["doc"]["validation_status"] == "PASSED", "Sollte Status PASSED haben"
    logger.info(f"[PASSED] Erstmaliger Import erfolgreich unter ID: {results[0]['doc']['beleg_id']}")

    # --- TEST 2: Identische Datei erneut importieren (MD5-Sperre) ---
    logger.info("\n--- TEST 2: Identische Datei importieren (MD5-Sperre) ---")
    with patch("src.parser.pdf_engine.pdf_engine.inspect_pdf", return_value=mock_pages_info_1):
        results2 = pipeline.process_pdf_archive(pdf1)
        
    assert len(results2) == 1, "Sollte 1 Ergebnis liefern"
    assert results2[0]["doc"]["validation_status"] == "DUBLITTE_MD5", "Status muss DUBLITTE_MD5 sein"
    assert results2[0]["saved_path"] == "DUBLITTE_MD5_NO_SAVE", "Dateipfad sollte nicht gespeichert sein"
    logger.info("[PASSED] MD5-Dublette erfolgreich blockiert und im Dashboard markiert.")

    # --- TEST 3: Metadaten-Matching (Verdacht auf Dublette) ---
    logger.info("\n--- TEST 3: Metadaten-Matching (Verdacht auf Dublette) ---")
    # Zweite Datei, anderes MD5, aber identischer Text (Metro, 2026-05-14, 142.50)
    mock_pages_info_2 = [
        {
            "page_num": 1,
            "text_snippet": "Metro Rechnung. Datum: 2026-05-14. Lieferant: Metro. Brutto: 142.50. USt: 9.32.",
            "full_text": "Rechnung Metro. Lieferant: Metro. Datum: 2026-05-14. Brutto: 142.50. Netto: 133.18. Steuer: 9.32. Seite 1 von 1."
        }
    ]
    with patch("src.parser.pdf_engine.pdf_engine.inspect_pdf", return_value=mock_pages_info_2):
        results3 = pipeline.process_pdf_archive(pdf2)
        
    assert len(results3) == 1, "Sollte 1 Ergebnis liefern"
    assert results3[0]["doc"]["validation_status"] == "DUBLITTE_VERDACHT", "Status muss DUBLITTE_VERDACHT sein"
    assert "DUBLITTEN" in results3[0]["saved_path"], "Datei muss im DUBLITTEN-Ordner liegen"
    logger.info(f"[PASSED] Metadaten-Dublette erfolgreich erkannt. Gespeichert unter: {results3[0]['saved_path']}")

    # --- TEST 4: Dashboard-Auswertung ---
    logger.info("\n--- TEST 4: Dashboard CSV Prüfung ---")
    with open(dashboard_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    # Header + 3 Datensätze
    assert len(lines) == 4, f"Dashboard CSV sollte 4 Zeilen enthalten, hat {len(lines)}"
    
    # Prüfe Zeilen-Inhalte
    logger.info(f"Dashboard Zeile 2 (Base): {lines[1].strip()}")
    logger.info(f"Dashboard Zeile 3 (MD5-Dup): {lines[2].strip()}")
    logger.info(f"Dashboard Zeile 4 (Meta-Dup): {lines[3].strip()}")
    
    assert "OFFEN" in lines[1], "Erster Beleg muss OFFEN sein"
    assert "DUBLITTE_MD5" in lines[2], "Zweiter Beleg muss DUBLITTE_MD5 sein"
    assert "DUBLITTE_VERDACHT" in lines[3], "Dritter Beleg muss DUBLITTE_VERDACHT sein"
    logger.info("[PASSED] Dashboard CSV enthält alle korrekten Stati.")

    cleanup_files()
    print("\n🏆 ALLE DUBLETTEN-TESTS ERFOLGREICH BESTANDEN!")

if __name__ == "__main__":
    try:
        run_tests()
    except Exception as e:
        logger.error(f"Test fehlgeschlagen: {e}")
        cleanup_files()
        sys.exit(1)
