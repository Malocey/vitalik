"""Sicherer Ordner-Workflow: PDF-Verarbeitung, Done-Markierung und CSV-Inventar."""

import argparse
import csv
import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import archive_pipeline
from pypdf import PdfReader


CSV_COLUMNS = [
    "Quelldatei", "Quellpfad", "Verarbeitungsstatus", "Dateigroesse_MB",
    "Datei_MD5", "Startseite", "Endseite", "Beleg_ID", "Dokumenttyp",
    "Lieferant_Aussteller", "Datum", "Rechnungsnummer", "Netto_EUR",
    "Steuer_EUR", "Brutto_EUR", "USt_Prozent", "Warengruppe",
    "SKR03_Konto", "Validierungsstatus", "Validierungsgrund", "Confidence",
    "PDF_Link", "Wiki_Pfad", "OCR_Pfad", "RAG_gelesen",
    "Persistenz_bestaetigt",
]


def _safe_csv_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_pdf(path: Path) -> int:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Datei fehlt oder ist leer.")
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ValueError("Datei besitzt keinen gültigen PDF-Header.")
    reader = PdfReader(str(path))
    page_count = len(reader.pages)
    if page_count == 0:
        raise ValueError("PDF enthält keine lesbaren Seiten.")
    if page_count > 2000:
        raise ValueError("PDF überschreitet das Sicherheitslimit von 2000 Seiten.")
    return page_count


def _write_report(report_path: Path, rows: List[Dict[str, Any]]) -> None:
    temporary_path = report_path.with_suffix(report_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _safe_csv_value(row.get(key, "")) for key in CSV_COLUMNS})
        handle.flush()
        os.fsync(handle.fileno())
    temporary_path.replace(report_path)


def process_folder(folder: Path, report_name: str = "Dokumenten_Uebersicht.csv") -> Dict[str, int]:
    folder = folder.resolve()
    if not folder.is_dir():
        raise NotADirectoryError(folder)
    lock_path = folder / ".document_processing.lock"
    lock_fd = None
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(lock_fd, str(os.getpid()).encode("ascii"))
    except FileExistsError as exc:
        raise RuntimeError(f"Ordner wird bereits verarbeitet: {lock_path}") from exc

    report_path = folder / report_name
    existing_rows: List[Dict[str, Any]] = []
    if report_path.exists():
        with report_path.open("r", encoding="utf-8-sig", newline="") as handle:
            existing_rows = list(csv.DictReader(handle, delimiter=";"))
    rows = existing_rows
    processed = failed = skipped = 0
    try:
        candidates = sorted(
            path for path in folder.glob("*.pdf")
            if not path.name.startswith("Done_")
        )
        for pdf_path in candidates:
            source_name = pdf_path.name
            rows = [row for row in rows if row.get("Quelldatei") != source_name]
            source_path = str(pdf_path.resolve())
            size_mb = round(pdf_path.stat().st_size / (1024 * 1024), 2)
            checksum = _md5(pdf_path)
            try:
                _validate_pdf(pdf_path)
                results = archive_pipeline.process_pdf_archive(pdf_path, source_action="done")
                done_path = pdf_path.with_name(f"Done_{source_name}")
                if not done_path.exists():
                    raise RuntimeError("Done-Markierung fehlt; Persistenz war nicht vollständig.")
                for result in results:
                    doc = result.get("doc", {})
                    verification = doc.get("persistence_verification", {})
                    rows.append({
                        "Quelldatei": source_name, "Quellpfad": str(done_path.resolve()),
                        "Verarbeitungsstatus": "DONE", "Dateigroesse_MB": size_mb,
                        "Datei_MD5": checksum, "Startseite": doc.get("start_seite"),
                        "Endseite": doc.get("end_seite"), "Beleg_ID": doc.get("beleg_id"),
                        "Dokumenttyp": doc.get("belegtyp"),
                        "Lieferant_Aussteller": doc.get("lieferant"), "Datum": doc.get("datum"),
                        "Rechnungsnummer": doc.get("rechnungsnummer"),
                        "Netto_EUR": doc.get("netto"), "Steuer_EUR": doc.get("steuer"),
                        "Brutto_EUR": doc.get("brutto"),
                        "USt_Prozent": doc.get("steuersatz_prozent"),
                        "Warengruppe": doc.get("warengruppe"),
                        "SKR03_Konto": doc.get("skr03_konto"),
                        "Validierungsstatus": doc.get("validation_status"),
                        "Validierungsgrund": doc.get("validation_reason") or result.get("reason"),
                        "Confidence": doc.get("confidence_score"),
                        "PDF_Link": result.get("saved_path"),
                        "Wiki_Pfad": doc.get("wiki_path"), "OCR_Pfad": doc.get("raw_text_path"),
                        "RAG_gelesen": doc.get("rag_read_verified"),
                        "Persistenz_bestaetigt": verification.get("ok"),
                    })
                processed += 1
            except Exception as exc:
                failed += 1
                rows.append({
                    "Quelldatei": source_name, "Quellpfad": source_path,
                    "Verarbeitungsstatus": "FEHLER", "Dateigroesse_MB": size_mb,
                    "Datei_MD5": checksum, "Validierungsgrund": str(exc),
                    "Persistenz_bestaetigt": False,
                })
            _write_report(report_path, rows)
        done_files = sorted(folder.glob("Done_*.pdf"))
        recorded_done_paths = {row.get("Quellpfad") for row in rows}
        for done_file in done_files:
            if str(done_file.resolve()) not in recorded_done_paths:
                rows.append({
                    "Quelldatei": done_file.name.removeprefix("Done_"),
                    "Quellpfad": str(done_file.resolve()),
                    "Verarbeitungsstatus": "BEREITS_DONE",
                    "Dateigroesse_MB": round(done_file.stat().st_size / (1024 * 1024), 2),
                    "Datei_MD5": _md5(done_file),
                    "PDF_Link": str(done_file.resolve()),
                })
        skipped = len(done_files)
        _write_report(report_path, rows)
        return {"processed": processed, "failed": failed, "skipped": skipped}
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if lock_path.exists():
            lock_path.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PDF-Ordner sicher verarbeiten")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--report", default="Dokumenten_Uebersicht.csv")
    args = parser.parse_args()
    result = process_folder(args.folder, args.report)
    print(
        f"Ordnerlauf abgeschlossen: {result['processed']} verarbeitet, "
        f"{result['failed']} Fehler, {result['skipped']} bereits Done."
    )
