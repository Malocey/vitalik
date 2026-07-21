#!/usr/bin/env python3
"""
Drive-Sorter für VG Delikatessen.
Teilt Dokumente aus einem Scan-Stapel auf, benennt sie nach dem standardisierten Schema:
- Gültig: YYYY-MM-DD_Lieferant_Bruttobetrag.pdf
- Ungültig/Fehlerhaft: YYYY-MM-DD_UNKNOWN_Lieferant.pdf
und sortiert sie in die Google-Drive-Matrix (bzw. lokale Mock-Matrix) ein.
Protokolliert alle Belege im VG_Zentral_Dashboard (Google Sheet / lokale CSV).
"""

import os
import re
import sys
import datetime
import logging
from pathlib import Path
from typing import Dict, Any, Tuple

# Windows UTF-8 Terminal Support
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Projektpfad für src Imports auflösen
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from src.core.config import MOCK_DRIVE_DIR
from src.parser.pdf_engine import pdf_engine
from src.drive.matrix_setup import GERMAN_MONTHS, authenticate_google_apis, find_or_create_folder
from src.core.rag_engine import rag_engine

logger = logging.getLogger("DriveSorter")

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    import io
    HAS_GOOGLE_LIBS = True
except ImportError:
    HAS_GOOGLE_LIBS = False


def determine_destination_folder(doc_data: Dict[str, Any]) -> str:
    """
    Bestimmt den Zielpfad basierend auf Business vs. Privat/Familie Logik.
    """
    text = doc_data.get("raw_text", "").lower()
    lieferant = doc_data.get("lieferant", "").lower()

    # 1. Geschäftlich (Business-Match)
    business_keywords = ["world wide food", "rv impex", "jensmann"]
    is_business = False
    for kw in business_keywords:
        if kw in text or kw in lieferant:
            is_business = True
            break

    if is_business:
        datum_str = doc_data.get("datum", datetime.datetime.now().strftime("%Y-%m-%d"))
        try:
            dt = datetime.datetime.strptime(datum_str, "%Y-%m-%d")
            year_str = str(dt.year)
            month_str = GERMAN_MONTHS.get(dt.month, f"{dt.month:02d}_Monat")
        except Exception:
            year_str = datetime.datetime.now().strftime("%Y")
            month_str = GERMAN_MONTHS.get(datetime.datetime.now().month, "00_Monat")

        belegtyp = doc_data.get("belegtyp", "Sonstiges")
        belegtyp_folder_map = {
            "Rechnung": "Rechnungen",
            "Angebot": "Angebote",
            "Lieferschein": "Lieferscheine",
            "Auftragsbestaetigung": "Auftragsbestaetigungen",
            "Mahnung": "Mahnungen",
            "Sonstiges": "Sonstiges"
        }
        beleg_subfolder = belegtyp_folder_map.get(belegtyp, "Sonstiges")
        return f"01_Eingangsarchiv/{year_str}/{month_str}/{beleg_subfolder}"

    # 2. Privat & Familie (Personen-Match)
    # Suche nach "<Vorname> Gebel"
    match = re.search(r"\b([a-zA-ZäöüÄÖÜß]+)\s+gebel\b", text)
    if match:
        vorname = match.group(1).capitalize()
        datum_str = doc_data.get("datum", datetime.datetime.now().strftime("%Y-%m-%d"))
        try:
            dt = datetime.datetime.strptime(datum_str, "%Y-%m-%d")
            year_str = str(dt.year)
        except Exception:
            year_str = datetime.datetime.now().strftime("%Y")

        return f"05_Privat_Familie/{vorname}_Gebel/{year_str}"

    # 3. Fallback, wenn nichts greift und es eigentlich "PASSED" war,
    # gehen wir standardmäßig ins Firmenarchiv
    datum_str = doc_data.get("datum", datetime.datetime.now().strftime("%Y-%m-%d"))
    try:
        dt = datetime.datetime.strptime(datum_str, "%Y-%m-%d")
        year_str = str(dt.year)
        month_str = GERMAN_MONTHS.get(dt.month, f"{dt.month:02d}_Monat")
    except Exception:
        year_str = datetime.datetime.now().strftime("%Y")
        month_str = GERMAN_MONTHS.get(datetime.datetime.now().month, "00_Monat")

    belegtyp = doc_data.get("belegtyp", "Sonstiges")
    belegtyp_folder_map = {
        "Rechnung": "Rechnungen",
        "Angebot": "Angebote",
        "Lieferschein": "Lieferscheine",
        "Auftragsbestaetigung": "Auftragsbestaetigungen",
        "Mahnung": "Mahnungen",
        "Sonstiges": "Sonstiges"
    }
    beleg_subfolder = belegtyp_folder_map.get(belegtyp, "Sonstiges")
    return f"01_Eingangsarchiv/{year_str}/{month_str}/{beleg_subfolder}"


def generate_standardized_filename(doc_data: Dict[str, Any]) -> Tuple[str, bool]:
    """
    Generiert den Zieldateinamen gemäß den Vorgaben:
    - Valider Beleg: YYYY-MM-DD_Lieferant_Bruttobetrag.pdf
    - Unleserlich/Fehlerhaft: YYYY-MM-DD_UNKNOWN_Lieferant.pdf
    Gibt (dateiname, passed_validation) zurück.
    """
    datum = str(doc_data.get("datum", "")).strip()
    lieferant = str(doc_data.get("lieferant", "")).strip()
    brutto = doc_data.get("brutto", 0.0)
    validation_status = doc_data.get("validation_status", "MANUAL_REVIEW_NEEDED")

    # Datum validieren (YYYY-MM-DD)
    date_pattern = r"^\d{4}-\d{2}-\d{2}$"
    is_date_valid = bool(re.match(date_pattern, datum)) and datum != "2026-07-01"

    # Lieferant validieren
    is_lieferant_valid = bool(lieferant) and lieferant.lower() not in [
        "unbekannter lieferant", "unbekannt", "unknown", ""
    ]

    # Brutto validieren
    is_brutto_valid = brutto is not None and isinstance(brutto, (int, float)) and brutto > 0.0

    # Allgemeine Gültigkeit prüfen
    passed = is_date_valid and is_lieferant_valid and is_brutto_valid and validation_status == "PASSED"

    # Lieferantennamen bereinigen
    clean_supplier = "Unbekannt"
    if lieferant:
        clean_supplier = re.sub(r"[^\w\-]", "_", lieferant)
        clean_supplier = re.sub(r"_+", "_", clean_supplier).strip("_")

    if passed:
        # Standard: YYYY-MM-DD_Lieferant_Bruttobetrag.pdf (z.B. 2026-05-14_Metro_142.50.pdf)
        filename = f"{datum}_{clean_supplier}_{brutto:.2f}.pdf"
    else:
        # Fallback: YYYY-MM-DD_UNKNOWN_Lieferant.pdf (z.B. 2026-07-21_UNKNOWN_Metro.pdf)
        fallback_date = datum if is_date_valid else datetime.datetime.now().strftime("%Y-%m-%d")
        filename = f"{fallback_date}_UNKNOWN_{clean_supplier}.pdf"

    return filename, passed


class DriveSorter:
    def __init__(self, mode: str = "auto", credentials_path: str = "credentials.json", service_account_path: str = "service_account.json"):
        self.credentials_path = credentials_path
        self.service_account_path = service_account_path
        
        if mode == "auto":
            if os.path.exists(service_account_path) or os.path.exists(credentials_path):
                self.mode = "real"
            else:
                self.mode = "mock"
        else:
            self.mode = mode

        self.creds = None
        self.drive_service = None
        self.sheets_service = None

        if self.mode == "real":
            try:
                self.creds = authenticate_google_apis(credentials_path, service_account_path)
                self.drive_service = build('drive', 'v3', credentials=self.creds)
                self.sheets_service = build('sheets', 'v4', credentials=self.creds)
            except Exception as e:
                logger.error(f"[DriveSorter] Google API Authentifizierung fehlgeschlagen: {e}. Fallback auf Mock.")
                self.mode = "mock"

    def check_md5_exists(self, md5_hash: str) -> bool:
        """Prüft, ob der MD5-Hash bereits im Dashboard oder im Obsidian-Wiki vorhanden ist."""
        if not md5_hash:
            return False

        # 1. Wiki-Prüfung
        from src.core.config import WIKI_DIR
        if WIKI_DIR.exists():
            for md_file in WIKI_DIR.glob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    if md5_hash in content:
                        logger.info(f"[DriveSorter] MD5-Treffer im Wiki: {md_file.name}")
                        return True
                except Exception:
                    pass

        # 2. Dashboard-Prüfung
        if self.mode == "mock":
            root_path = MOCK_DRIVE_DIR / "[ VG_Delikatessen_Zentrale ]"
            dashboard_file = root_path / "📊 VG_Zentral_Dashboard.csv"
            if dashboard_file.exists():
                try:
                    with open(dashboard_file, "r", encoding="utf-8") as f:
                        for line in f:
                            parts = line.strip().split(",")
                            # MD5 ist an index 16 (letzte Spalte)
                            if len(parts) > 16 and parts[16] == md5_hash:
                                logger.info(f"[DriveSorter-Mock] MD5-Treffer im Dashboard CSV")
                                return True
                except Exception as e:
                    logger.error(f"[DriveSorter] Fehler bei MD5-CSV-Prüfung: {e}")
        else:
            try:
                root_id = find_or_create_folder(self.drive_service, "[ VG_Delikatessen_Zentrale ]")
                sheet_name = "📊 VG_Zentral_Dashboard"
                query = f"name = '{sheet_name}' and '{root_id}' in parents and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
                results = self.drive_service.files().list(q=query, spaces='drive', fields='files(id)').execute()
                files = results.get('files', [])
                if files:
                    spreadsheet_id = files[0]['id']
                    result = self.sheets_service.spreadsheets().values().get(
                        spreadsheetId=spreadsheet_id,
                        range='Sheet1!Q:Q'
                    ).execute()
                    rows = result.get('values', [])
                    for row in rows:
                        if row and row[0] == md5_hash:
                            logger.info(f"[DriveSorter-Real] MD5-Treffer im Google Sheet Dashboard")
                            return True
            except Exception as e:
                logger.error(f"[DriveSorter] Fehler bei MD5-Sheet-Prüfung: {e}")

        return False

    def check_metadata_exists(self, supplier: str, brutto: float, date_str: str) -> bool:
        """Prüft, ob ein Beleg mit gleichen Metadaten (Lieferant, Betrag, Datum) bereits existiert."""
        if not supplier or not brutto or not date_str:
            return False

        clean_sup = supplier.lower().strip()
        brutto_str = f"{brutto:.2f}"

        if self.mode == "mock":
            root_path = MOCK_DRIVE_DIR / "[ VG_Delikatessen_Zentrale ]"
            dashboard_file = root_path / "📊 VG_Zentral_Dashboard.csv"
            if dashboard_file.exists():
                try:
                    with open(dashboard_file, "r", encoding="utf-8") as f:
                        next(f) # Skip header
                        for line in f:
                            parts = line.strip().split(",")
                            if len(parts) > 9:
                                c_date = parts[1].strip()
                                c_sup = parts[2].strip().lower()
                                c_brutto = parts[4].strip()
                                if c_date == date_str and c_sup == clean_sup and c_brutto == brutto_str:
                                    logger.info(f"[DriveSorter-Mock] Metadaten-Treffer im Dashboard CSV")
                                    return True
                except Exception as e:
                    logger.error(f"[DriveSorter] Fehler bei Metadaten-CSV-Prüfung: {e}")
        else:
            try:
                root_id = find_or_create_folder(self.drive_service, "[ VG_Delikatessen_Zentrale ]")
                sheet_name = "📊 VG_Zentral_Dashboard"
                query = f"name = '{sheet_name}' and '{root_id}' in parents and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
                results = self.drive_service.files().list(q=query, spaces='drive', fields='files(id)').execute()
                files = results.get('files', [])
                if files:
                    spreadsheet_id = files[0]['id']
                    result = self.sheets_service.spreadsheets().values().get(
                        spreadsheetId=spreadsheet_id,
                        range='Sheet1!A2:Q'
                    ).execute()
                    rows = result.get('values', [])
                    for row in rows:
                        if len(row) > 9:
                            c_date = row[1].strip()
                            c_sup = row[2].strip().lower()
                            try:
                                c_brutto = f"{float(row[4].replace(';', ',')):.2f}"
                            except ValueError:
                                c_brutto = ""
                            if c_date == date_str and c_sup == clean_sup and c_brutto == brutto_str:
                                logger.info(f"[DriveSorter-Real] Metadaten-Treffer im Google Sheet Dashboard")
                                return True
            except Exception as e:
                logger.error(f"[DriveSorter] Fehler bei Metadaten-Sheet-Prüfung: {e}")

        return False

    def sort_and_save_pdf(self, input_pdf_path: Path, start_page: int, end_page: int, doc_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Zerschneidet das Eingabe-PDF und sortiert es in den entsprechenden Ordner.
        - Gültig -> 01_Eingangsarchiv/YYYY/MM_Monat/
        - Ungültig -> 04_Pruefung_Erforderlich/
        - Dublettenverdacht -> 04_Pruefung_Erforderlich/DUBLITTEN/
        - MD5-Dublette -> In Dashboard eintragen mit Status DUBLITTE_MD5, keine Dateiablage
        """
        md5_hash = doc_data.get("md5_hash", "")
        
        # 1. MD5-Prüfung
        if md5_hash and self.check_md5_exists(md5_hash):
            logger.warning(f"[DriveSorter] MD5-Dublette erkannt: {md5_hash}")
            doc_data["validation_status"] = "DUBLITTE_MD5"
            filename, _ = generate_standardized_filename(doc_data)
            
            if self.mode == "mock":
                root_path = MOCK_DRIVE_DIR / "[ VG_Delikatessen_Zentrale ]"
                beleg_id = self._update_dashboard_mock(root_path, doc_data, Path("DUBLITTE_MD5_NO_SAVE"))
            else:
                root_id = find_or_create_folder(self.drive_service, "[ VG_Delikatessen_Zentrale ]")
                beleg_id = self._update_dashboard_real(root_id, doc_data, "DUBLITTE_MD5_NO_SAVE")
                
            return {
                "saved_path": "DUBLITTE_MD5_NO_SAVE",
                "passed": False,
                "filename": filename,
                "destination_folder": "None",
                "beleg_id": beleg_id
            }

        # 2. Name generieren
        filename, passed = generate_standardized_filename(doc_data)
        doc_data["validation_status"] = "PASSED" if passed else "MANUAL_REVIEW_NEEDED"

        # 3. Metadaten-Matching
        supplier = doc_data.get("lieferant", "")
        brutto = doc_data.get("brutto", 0.0)
        date_str = doc_data.get("datum", "")
        
        is_metadata_dup = self.check_metadata_exists(supplier, brutto, date_str)
        
        if is_metadata_dup:
            logger.warning(f"[DriveSorter] Metadaten-Dublettenverdacht erkannt für {supplier} - {brutto} EUR")
            doc_data["validation_status"] = "DUBLITTE_VERDACHT"
            doc_data["validation_reason"] = "Verdacht auf Dublette! Gleicher Beleg (Lieferant, Betrag, Datum) bereits erfasst."
            passed = False

        if self.mode == "mock":
            return self._sort_and_save_mock(input_pdf_path, start_page, end_page, filename, passed, doc_data, is_metadata_dup)
        else:
            return self._sort_and_save_real(input_pdf_path, start_page, end_page, filename, passed, doc_data, is_metadata_dup)

    def _sort_and_save_mock(self, input_pdf_path: Path, start_page: int, end_page: int, filename: str, passed: bool, doc_data: Dict[str, Any], is_metadata_dup: bool = False) -> Dict[str, Any]:
        """Lokale Speicherung im Mock Drive."""
        root_path = MOCK_DRIVE_DIR / "[ VG_Delikatessen_Zentrale ]"
        root_path.mkdir(parents=True, exist_ok=True)

        if is_metadata_dup:
            dest_folder_name = "04_Pruefung_Erforderlich/DUBLITTEN"
            target_dir = root_path / "04_Pruefung_Erforderlich" / "DUBLITTEN"
        elif passed:
            dest_folder_name = determine_destination_folder(doc_data)
            target_dir = root_path / Path(dest_folder_name)
        else:
            dest_folder_name = "04_Pruefung_Erforderlich"
            target_dir = root_path / "04_Pruefung_Erforderlich"

        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename

        pdf_engine.extract_single_document(input_pdf_path, start_page, end_page, target_path)
        logger.info(f"[DriveSorter-Mock] Datei gespeichert: {target_path}")

        beleg_id = self._update_dashboard_mock(root_path, doc_data, target_path)
        doc_data["beleg_id"] = beleg_id

        # In FTS5 indizieren
        rag_engine.index_beleg(doc_data, beleg_id)

        return {
            "saved_path": str(target_path),
            "passed": passed,
            "filename": filename,
            "destination_folder": dest_folder_name,
            "beleg_id": beleg_id
        }

    def _sort_and_save_real(self, input_pdf_path: Path, start_page: int, end_page: int, filename: str, passed: bool, doc_data: Dict[str, Any], is_metadata_dup: bool = False) -> Dict[str, Any]:
        """Speicherung in Google Drive."""
        temp_dir = Path("data/temp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file_path = temp_dir / f"temp_{filename}"

        pdf_engine.extract_single_document(input_pdf_path, start_page, end_page, temp_file_path)

        try:
            root_id = find_or_create_folder(self.drive_service, "[ VG_Delikatessen_Zentrale ]")

            if is_metadata_dup:
                pruefung_id = find_or_create_folder(self.drive_service, "04_Pruefung_Erforderlich", parent_id=root_id)
                target_folder_id = find_or_create_folder(self.drive_service, "DUBLITTEN", parent_id=pruefung_id)
                dest_folder_name = "04_Pruefung_Erforderlich/DUBLITTEN"
            elif passed:
                dest_folder_name = determine_destination_folder(doc_data)
                parts = dest_folder_name.split("/")
                current_parent_id = root_id
                for part in parts:
                    current_parent_id = find_or_create_folder(self.drive_service, part, parent_id=current_parent_id)
                target_folder_id = current_parent_id
            else:
                target_folder_id = find_or_create_folder(self.drive_service, "04_Pruefung_Erforderlich", parent_id=root_id)
                dest_folder_name = "04_Pruefung_Erforderlich"

            file_bytes = temp_file_path.read_bytes()
            media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype='application/pdf', resumable=True)
            
            query = f"name = '{filename}' and '{target_folder_id}' in parents and trashed = false"
            results = self.drive_service.files().list(q=query, spaces='drive', fields='files(id)').execute()
            files = results.get('files', [])

            if files:
                file_id = files[0]['id']
                file = self.drive_service.files().update(fileId=file_id, media_body=media, fields='id, webViewLink').execute()
                logger.info(f"[DriveSorter-Real] Datei überschrieben (ID: {file_id})")
            else:
                file_metadata = {
                    'name': filename,
                    'parents': [target_folder_id]
                }
                file = self.drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
                file_id = file.get('id')
                logger.info(f"[DriveSorter-Real] Datei hochgeladen (ID: {file_id})")

            web_view_link = file.get('webViewLink', f"https://drive.google.com/open?id={file_id}")

            beleg_id = self._update_dashboard_real(root_id, doc_data, web_view_link)
            doc_data["beleg_id"] = beleg_id

            # In FTS5 indizieren
            rag_engine.index_beleg(doc_data, beleg_id)

            return {
                "saved_path": web_view_link,
                "passed": passed,
                "filename": filename,
                "destination_folder": dest_folder_name,
                "beleg_id": beleg_id
            }

        finally:
            # Temp Datei entfernen
            if temp_file_path.exists():
                temp_file_path.unlink()

    def _update_dashboard_mock(self, root_path: Path, doc_data: Dict[str, Any], file_path: Path) -> str:
        """Trägt Daten in die lokale Dashboard CSV ein."""
        dashboard_file = root_path / "📊 VG_Zentral_Dashboard.csv"
        
        # Zeilen zählen für Beleg-ID
        row_count = 0
        if dashboard_file.exists():
            try:
                with open(dashboard_file, "r", encoding="utf-8") as f:
                    row_count = len(f.readlines()) - 1
            except Exception:
                pass
        else:
            # Erstelle mit Header
            headers = [
                "Beleg-ID", "Datum", "Lieferant", "Kategorie", "Bruttobetrag (€)", 
                "Nettobetrag (€)", "USt-Satz (%)", "USt-Betrag (€)", "Soll-Konto (SKR03)", 
                "Buchungsstatus", "Zahlungsziel", "Skonto-Frist", "Skonto-Satz (%)", 
                "sevDesk-ID", "Google Drive PDF Link", "Letzte Änderung", "MD5-Hash"
            ]
            with open(dashboard_file, "w", encoding="utf-8") as f:
                f.write(",".join(headers) + "\n")

        beleg_id = f"VG-{row_count + 1:04d}"
        
        # Felder vorbereiten
        datum = doc_data.get("datum", "")
        lieferant = doc_data.get("lieferant", "")
        kategorie_val = doc_data.get("warengruppe", "Unbekannt")
        belegtyp_val = doc_data.get("belegtyp", "Sonstiges")
        kategorie = f"{belegtyp_val} ({kategorie_val})" if kategorie_val != "Unbekannt" else belegtyp_val
        brutto = f"{doc_data.get('brutto', 0.0):.2f}"
        netto = f"{doc_data.get('netto', 0.0):.2f}"
        ust_sat = f"{doc_data.get('steuersatz_prozent', 7.0 if doc_data.get('steuer', 0.0) > 0 else 0.0):.1f}"
        ust_bet = f"{doc_data.get('steuer', 0.0):.2f}"
        skr03 = doc_data.get("skr03_konto", "3400")
        
        # Status
        val_status = doc_data.get("validation_status")
        if val_status in ["DUBLITTE_MD5", "DUBLITTE_VERDACHT"]:
            status = val_status
        else:
            status = "OFFEN" if val_status == "PASSED" else "PRUEFUNG_ERFORDERLICH"
        
        link = str(file_path.absolute())
        change_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        md5 = doc_data.get("md5_hash", "")

        row_data = [
            beleg_id, datum, lieferant, kategorie, brutto, netto, ust_sat, 
            ust_bet, skr03, status, "", "", "", "", link, change_time, md5
        ]
        
        # Sicherstellen, dass keine Kommas in den String-Werten das CSV-Format zerstören
        row_cleaned = [str(val).replace(",", ";") for val in row_data]

        with open(dashboard_file, "a", encoding="utf-8") as f:
            f.write(",".join(row_cleaned) + "\n")

        logger.info(f"[DriveSorter-Mock] Dashboard CSV aktualisiert. Neue Zeile ID: {beleg_id}")
        return beleg_id

    def _update_dashboard_real(self, root_id: str, doc_data: Dict[str, Any], web_view_link: str) -> str:
        """Fügt eine Zeile im Google Sheet Dashboard hinzu."""
        sheet_name = "📊 VG_Zentral_Dashboard"
        query = f"name = '{sheet_name}' and '{root_id}' in parents and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
        results = self.drive_service.files().list(q=query, spaces='drive', fields='files(id)').execute()
        files = results.get('files', [])

        if not files:
            raise FileNotFoundError("Google Sheet Zentral-Dashboard nicht gefunden. Führe zuerst setup aus.")
        
        spreadsheet_id = files[0]['id']

        # Get existing row count to determine Beleg-ID
        result = self.sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Sheet1!A:A'
        ).execute()
        rows = result.get('values', [])
        row_count = len(rows) - 1 if rows else 0
        beleg_id = f"VG-{row_count + 1:04d}"

        # Werte zusammenstellen
        datum = doc_data.get("datum", "")
        lieferant = doc_data.get("lieferant", "")
        kategorie_val = doc_data.get("warengruppe", "Unbekannt")
        belegtyp_val = doc_data.get("belegtyp", "Sonstiges")
        kategorie = f"{belegtyp_val} ({kategorie_val})" if kategorie_val != "Unbekannt" else belegtyp_val
        brutto = doc_data.get('brutto', 0.0)
        netto = doc_data.get('netto', 0.0)
        ust_sat = doc_data.get('steuersatz_prozent', 7.0 if doc_data.get('steuer', 0.0) > 0 else 0.0)
        ust_bet = doc_data.get('steuer', 0.0)
        skr03 = doc_data.get("skr03_konto", "3400")
        
        # Status
        val_status = doc_data.get("validation_status")
        if val_status in ["DUBLITTE_MD5", "DUBLITTE_VERDACHT"]:
            status = val_status
        else:
            status = "OFFEN" if val_status == "PASSED" else "PRUEFUNG_ERFORDERLICH"
            
        change_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        md5 = doc_data.get("md5_hash", "")

        row_values = [
            beleg_id, datum, lieferant, kategorie, brutto, netto, ust_sat, 
            ust_bet, skr03, status, "", "", "", "", web_view_link, change_time, md5
        ]

        body = {
            'values': [row_values]
        }

        # Zeile anhängen
        self.sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range='Sheet1!A2',
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()

        logger.info(f"[DriveSorter-Real] Google Sheet aktualisiert. Neue Zeile ID: {beleg_id}")
        return beleg_id
