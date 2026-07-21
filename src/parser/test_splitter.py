#!/usr/bin/env python3
"""
Testskript für die PDF Splitting, Naming und Sorting Engine.
Mockt die OCR-Texte und die LLM-Vervollständigung, um die Heuristiken
und Speicherprozeduren deterministisch zu prüfen.
"""

import os
import re
import sys
import shutil
import datetime
import tempfile
from pypdf import PdfWriter
from pathlib import Path
from typing import Dict, Any

# Windows UTF-8 Terminal Support
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Projektpfad für src Imports auflösen
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from src.parser.pdf_engine import pdf_engine
from src.parser.analyzer import document_analyzer
from src.core.local_llm_client import default_llm_client
from src.drive.sorter import DriveSorter, generate_standardized_filename
import src.drive.sorter as sorter_module
from pipeline import archive_pipeline
from src.core.mocks import mock_sevdesk, mock_telegram
from src.core.rag_engine import rag_engine
from src.core.config import MOCK_DRIVE_DIR
from src.core.contact_memory import ContactMemory
from src.core.document_jobs import DocumentJobEngine
from src.core.job_repository import JobRepository
from src.core.pipeline_job_adapter import PipelineJobAdapter
import src.parser.analyzer as analyzer_module


def test_splitting_and_naming():
    print("=== STARTE VERIFIKATIONSTEST FÜR SPLITTING, NAMING & SORTING ===")

    # 1. Mock-Daten vorbereiten
    # Wir simulieren einen 4-seitigen Scan-Stapel mit 3 getrennten Belegen:
    # - Beleg 1: Metro, 2 Seiten (Seite 1-2) -> Gültig
    # - Beleg 2: Edeka, 1 Seite (Seite 3) -> Gültig
    # - Beleg 3: Unleserlicher Scan, 1 Seite (Seite 4) -> Ungültig (Fallback)
    mock_pages = [
        {
            "page_num": 1,
            "text_snippet": "Rechnung. Lieferant: Metro. Datum: 2026-05-14. Brutto: 142.50. Netto: 133.18. Steuer: 9.32. Seite 1 von 2.",
            "full_text": "Rechnung. Lieferant: Metro. Datum: 2026-05-14. Brutto: 142.50. Netto: 133.18. Steuer: 9.32. Seite 1 von 2."
        },
        {
            "page_num": 2,
            "text_snippet": "Posten 1: Rindfleisch. Seite 2 von 2.",
            "full_text": "Posten 1: Rindfleisch. Seite 2 von 2."
        },
        {
            "page_num": 3,
            "text_snippet": "Rechnung Edeka Großmarkt. Datum: 2026-06-15. Lieferant: Edeka. Brutto: 85.00. Netto: 79.44. Steuer: 5.56. Seite 1 von 1.",
            "full_text": "Rechnung Edeka Großmarkt. Datum: 2026-06-15. Lieferant: Edeka. Brutto: 85.00. Netto: 79.44. Steuer: 5.56. Seite 1 von 1."
        },
        {
            "page_num": 4,
            "text_snippet": "Ein stark verschmutzter Beleg. Keine Beträge lesbar. Confidence sehr gering.",
            "full_text": "Ein stark verschmutzter Beleg ohne erkennbare Rechnungsnummer. Keine Beträge lesbar. Die OCR-Confidence ist sehr gering. Manuelle Prüfung erforderlich."
        }
    ]

    # 2. Monkey-Patching für pdf_engine und LLM-Client
    # Speichere die originalen Methoden
    original_inspect = pdf_engine.inspect_pdf
    original_generate = default_llm_client.generate_completion
    original_mock_drive_dir = sorter_module.MOCK_DRIVE_DIR
    original_index_verify = archive_pipeline.sorter._index_and_verify_beleg
    original_post_voucher = mock_sevdesk.post_voucher
    original_telegram = mock_telegram.send_approval_request
    original_rag_assignment = rag_engine.match_sevdesk_assignment
    original_rag_search = rag_engine.search
    original_job_adapter = archive_pipeline.job_adapter
    original_contact_store = archive_pipeline.contact_store
    original_analyzer_contact_memory = analyzer_module.contact_memory
    temporary_root = Path(tempfile.mkdtemp(prefix="vitalik_splitter_test_"))
    test_mock_drive_dir = temporary_root / "Drive"
    sorter_module.MOCK_DRIVE_DIR = test_mock_drive_dir
    archive_pipeline.sorter._index_and_verify_beleg = lambda doc, beleg_id: doc.update({
        "beleg_id": beleg_id,
        "persistence_verified": True,
        "persistence_verification": {"ok": True},
    })
    mock_sevdesk.post_voucher = lambda doc: {"id": "TEST"}
    mock_telegram.send_approval_request = lambda doc: "TEST"
    rag_engine.match_sevdesk_assignment = lambda text: {"supplier": None, "articles": []}
    rag_engine.search = lambda *args, **kwargs: []
    test_contact_memory = ContactMemory(temporary_root / "rag_index.db")
    archive_pipeline.contact_store = test_contact_memory
    analyzer_module.contact_memory = test_contact_memory
    archive_pipeline.job_adapter = PipelineJobAdapter(DocumentJobEngine(
        repository=JobRepository(str(temporary_root / "document_jobs.db"))
    ))

    # Mock inspect_pdf
    pdf_engine.inspect_pdf = lambda path: mock_pages

    def mock_generate_completion(prompt, system_prompt=None, temperature=0.1, json_mode=False):
        belegtext = ""
        if "### Belegtext:" in prompt:
            parts = prompt.split("### Belegtext:")
            if len(parts) > 1:
                belegtext = parts[1].split("### Anforderung")[0]
        else:
            belegtext = prompt
        if "Metro" in belegtext:
            return """{
              "lieferant": "Metro",
              "datum": "2026-05-14",
              "netto": 133.18,
              "steuer": 9.32,
              "brutto": 142.50,
              "rechnungsnummer": "RE-1000",
              "confidence_score": 0.98,
              "warengruppe": "Fleischwaren"
            }"""
        elif "Edeka" in belegtext:
            return """{
              "lieferant": "Edeka",
              "datum": "2026-06-15",
              "netto": 79.44,
              "steuer": 5.56,
              "brutto": 85.00,
              "rechnungsnummer": "RE-2000",
              "confidence_score": 0.97,
              "warengruppe": "Fleischwaren"
            }"""
        else:
            # Ungültiges/Fallback JSON
            return """{
              "lieferant": "Unbekannter Lieferant",
              "datum": "2026-07-01",
              "netto": 0.0,
              "steuer": 0.0,
              "brutto": 0.0,
              "rechnungsnummer": "UNBEKANNT",
              "confidence_score": 0.30,
              "warengruppe": "Unbekannt"
            }"""

    default_llm_client.generate_completion = mock_generate_completion

    # 3. Temporären Teststapel erstellen und Pipeline ausführen
    test_pdf_path = Path("test_misch_scan.pdf")
    writer = PdfWriter()
    for index in range(4):
        writer.add_blank_page(width=595 + index, height=842)
    with test_pdf_path.open("wb") as handle:
        writer.write(handle)

    # Lösche alten Test-Mock-Ordner, falls vorhanden, für sauberen Test
    mock_root = test_mock_drive_dir / "[ VG_Delikatessen_Zentrale ]"
    if mock_root.exists():
        shutil.rmtree(mock_root)

    try:
        # Pipeline ausführen
        results = archive_pipeline.process_pdf_archive(test_pdf_path, source_action="keep")
        results.sort(key=lambda item: item["doc"]["start_seite"])

        # 4. Assertions & Überprüfungen
        print("\n--- TESTAUSWERTUNG ---")
        assert len(results) == 3, f"Fehler: Es wurden {len(results)} statt 3 Belege extrahiert."
        print(f"[PASSED] 3 Belege erfolgreich aus Stapel extrahiert.")

        # Beleg 1 prüfen (Metro, 2 Seiten, gültig)
        doc1 = results[0]["doc"]
        assert doc1["start_seite"] == 1 and doc1["end_seite"] == 2, "Beleg 1 Seitenbereich inkorrekt."
        assert doc1["lieferant"] == "Metro", "Beleg 1 Lieferant inkorrekt."
        filename1, passed1 = generate_standardized_filename(doc1)
        assert passed1 is True, "Beleg 1 sollte die Validierung bestehen."
        assert filename1 == "2026-05-14_Metro_142.50.pdf", f"Beleg 1 Dateiname falsch: {filename1}"
        
        # Dateipfad prüfen
        path1 = mock_root / "01_Eingangsarchiv" / "2026" / "05_Mai" / "Rechnungen" / filename1
        assert path1.exists(), f"Datei 1 existiert nicht am Zielort: {path1}"
        print(f"[PASSED] Beleg 1 (Metro) korrekt gesplittet, benannt und sortiert: {path1.name}")

        # Beleg 2 prüfen (Edeka, 1 Seite, gültig)
        doc2 = results[1]["doc"]
        assert doc2["start_seite"] == 3 and doc2["end_seite"] == 3, "Beleg 2 Seitenbereich inkorrekt."
        assert doc2["lieferant"] == "Edeka", "Beleg 2 Lieferant inkorrekt."
        filename2, passed2 = generate_standardized_filename(doc2)
        assert passed2 is True, "Beleg 2 sollte die Validierung bestehen."
        assert filename2 == "2026-06-15_Edeka_85.00.pdf", f"Beleg 2 Dateiname falsch: {filename2}"

        # Dateipfad prüfen
        path2 = mock_root / "01_Eingangsarchiv" / "2026" / "06_Juni" / "Rechnungen" / filename2
        assert path2.exists(), f"Datei 2 existiert nicht am Zielort: {path2}"
        print(f"[PASSED] Beleg 2 (Edeka) korrekt gesplittet, benannt und sortiert: {path2.name}")

        # Beleg 3 prüfen (Unleserlich, ungültig -> Fallback in 04_Pruefung_Erforderlich)
        doc3 = results[2]["doc"]
        assert doc3["start_seite"] == 4 and doc3["end_seite"] == 4, "Beleg 3 Seitenbereich inkorrekt."
        filename3, passed3 = generate_standardized_filename(doc3)
        assert passed3 is False, "Beleg 3 sollte die Validierung nicht bestehen."
        
        # Format des Fallback-Namens prüfen: YYYY-MM-DD_UNKNOWN_Lieferant.pdf
        # Da Datum unleserlich (2026-07-01 default), greift heutiges Datum für Fallback
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        assert filename3 == f"{today_str}_UNKNOWN_Unbekannter_Lieferant.pdf", f"Beleg 3 Dateiname falsch: {filename3}"

        # Dateipfad prüfen
        path3 = mock_root / "04_Pruefung_Erforderlich" / filename3
        assert path3.exists(), f"Datei 3 existiert nicht am Zielort: {path3}"
        print(f"[PASSED] Beleg 3 (Ungültig) ging in Fehlerordner: {path3.name}")

        # 5. Dashboard CSV überprüfen
        csv_path = mock_root / "📊 VG_Zentral_Dashboard.csv"
        assert csv_path.exists(), "Dashboard CSV wurde nicht erstellt."
        
        with open(csv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        # Header + 3 Belege = 4 Zeilen
        assert len(lines) == 4, f"Dashboard CSV hat {len(lines)} Zeilen statt 4."
        print(f"[PASSED] Dashboard CSV enthält genau {len(lines)-1} Einträge.")

        # Parallele Worker dürfen in beliebiger Reihenfolge abschließen.
        line1 = next(line.strip().split(",") for line in lines[1:] if ",Metro," in line)
        assert line1[0].startswith("VG-"), f"Metro ID falsch: {line1[0]}"
        assert line1[1] == "2026-05-14", f"Metro Datum falsch: {line1[1]}"
        assert line1[2] == "Metro", f"Metro Lieferant falsch: {line1[2]}"
        assert line1[4] == "142.50", f"Metro Brutto falsch: {line1[4]}"
        assert line1[9] == "OFFEN", f"Metro Status falsch: {line1[9]}"

        # Ungültigen Eintrag unabhängig von der Abschlussreihenfolge prüfen.
        line3 = next(line.strip().split(",") for line in lines[1:] if ",Unbekannter Lieferant," in line)
        assert line3[0].startswith("VG-"), f"Fehlerbeleg ID falsch: {line3[0]}"
        assert line3[9] == "PRUEFUNG_ERFORDERLICH", f"Fehlerbeleg Status falsch: {line3[9]}"
        print(f"[PASSED] Dashboard-Datenzeilen sind vollständig und korrekt strukturiert.")

        print("\n🏆 ALLE TESTS ERFOLGREICH BESTANDEN!")

    finally:
        # Clean up
        if test_pdf_path.exists():
            test_pdf_path.unlink()
        # Restore original functions
        pdf_engine.inspect_pdf = original_inspect
        default_llm_client.generate_completion = original_generate
        sorter_module.MOCK_DRIVE_DIR = original_mock_drive_dir
        archive_pipeline.sorter._index_and_verify_beleg = original_index_verify
        mock_sevdesk.post_voucher = original_post_voucher
        mock_telegram.send_approval_request = original_telegram
        rag_engine.match_sevdesk_assignment = original_rag_assignment
        rag_engine.search = original_rag_search
        archive_pipeline.job_adapter = original_job_adapter
        archive_pipeline.contact_store = original_contact_store
        analyzer_module.contact_memory = original_analyzer_contact_memory
        shutil.rmtree(temporary_root, ignore_errors=True)


if __name__ == "__main__":
    test_splitting_and_naming()
