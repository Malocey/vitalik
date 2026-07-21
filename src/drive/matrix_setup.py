#!/usr/bin/env python3
"""
Drive-Matrix Setup für VG Delikatessen.
Initialisiert die Google-Drive-Ordnerstruktur für den Kunden Vitalik Gebel
und erstellt das Google Sheet Zentral-Dashboard.
Unterstützt Service Accounts, OAuth 2.0 Desktop-Flow und einen lokalen Mock-Fallback.
"""

import os
import sys
import datetime
import argparse
from pathlib import Path

# Windows UTF-8 Terminal Support
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Projektpfad für src Imports auflösen
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from src.core.config import MOCK_DRIVE_DIR

# Lokale German-Months Übersetzung
GERMAN_MONTHS = {
    1: "01_Januar", 2: "02_Februar", 3: "03_Maerz", 4: "04_April",
    5: "05_Mai", 6: "06_Juni", 7: "07_Juli", 8: "08_August",
    9: "09_September", 10: "10_Oktober", 11: "11_November", 12: "12_Dezember"
}

# Google API Importprüfung
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    HAS_GOOGLE_LIBS = True
except ImportError:
    HAS_GOOGLE_LIBS = False


def authenticate_google_apis(credentials_path: str, service_account_path: str):
    """
    Versucht sich mit Google Drive und Google Sheets APIs zu verbinden.
    1. Service Account (falls Datei existiert)
    2. OAuth Desktop Flow (falls credentials.json existiert)
    """
    if not HAS_GOOGLE_LIBS:
        raise ImportError(
            "Google API Client Bibliotheken fehlen. Bitte führen Sie aus:\n"
            "pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )

    creds = None
    scopes = [
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/spreadsheets'
    ]

    # 1. Service Account Flow
    if service_account_path and os.path.exists(service_account_path):
        try:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                service_account_path, scopes=scopes
            )
            print(f"[Google Auth] Authentifiziert mit Service Account: {service_account_path}")
            return creds
        except Exception as e:
            print(f"[Google Auth] Service-Account-Verbindung fehlgeschlagen: {e}")

    # 2. OAuth Desktop Application Flow
    token_path = Path("token.json")
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path or not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"Weder '{service_account_path}' noch '{credentials_path}' gefunden.\n"
                    "Bitte legen Sie die Zugangsdaten bereit oder starten Sie mit dem Argument '--mode mock'."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
            creds = flow.run_local_server(port=0)
        # Token sichern für künftige Aufrufe
        with open(token_path, 'w', encoding="utf-8") as token:
            token.write(creds.to_json())

    print("[Google Auth] Authentifiziert mit OAuth 2.0 Desktop-Flow")
    return creds


def find_or_create_folder(drive_service, name: str, parent_id: str = None) -> str:
    """Sucht nach einem Ordner im Google Drive oder legt ihn an."""
    query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])

    if files:
        folder_id = files[0]['id']
        print(f"[Drive] Ordner '{name}' existiert bereits (ID: {folder_id})")
        return folder_id

    # Ordner erstellen
    metadata = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    if parent_id:
        metadata['parents'] = [parent_id]

    folder = drive_service.files().create(body=metadata, fields='id').execute()
    folder_id = folder.get('id')
    print(f"[Drive] Ordner '{name}' erfolgreich angelegt (ID: {folder_id})")
    return folder_id


def find_or_create_dashboard_sheet(drive_service, sheets_service, name: str, parent_id: str) -> str:
    """Erstellt das Zentral-Dashboard Google Sheet im angegebenen Ordner, falls nicht vorhanden."""
    query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])

    if files:
        spreadsheet_id = files[0]['id']
        print(f"[Drive] Google Sheet '{name}' existiert bereits (ID: {spreadsheet_id})")
        return spreadsheet_id

    # Spreadsheet erstellen
    spreadsheet_meta = {
        'properties': {
            'title': name
        }
    }
    spreadsheet = sheets_service.spreadsheets().create(body=spreadsheet_meta, fields='spreadsheetId').execute()
    spreadsheet_id = spreadsheet.get('spreadsheetId')
    print(f"[Sheets] Google Sheet '{name}' erstellt (ID: {spreadsheet_id})")

    # In den Zielordner verschieben
    file = drive_service.files().get(fileId=spreadsheet_id, fields='parents').execute()
    previous_parents = ",".join(file.get('parents', []))
    drive_service.files().update(
        fileId=spreadsheet_id,
        addParents=parent_id,
        removeParents=previous_parents,
        fields='id, parents'
    ).execute()
    print(f"[Drive] Google Sheet in Stammordner '{parent_id}' verschoben.")

    # Spaltenüberschriften schreiben
    headers = [
        "Beleg-ID", "Datum", "Lieferant", "Kategorie", "Bruttobetrag (€)", 
        "Nettobetrag (€)", "USt-Satz (%)", "USt-Betrag (€)", "Soll-Konto (SKR03)", 
        "Buchungsstatus", "Zahlungsziel", "Skonto-Frist", "Skonto-Satz (%)", 
        "sevDesk-ID", "Google Drive PDF Link", "Letzte Änderung"
    ]

    body = {
        'values': [headers]
    }
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range='Sheet1!A1',
        valueInputOption='RAW',
        body=body
    ).execute()

    # Layout anpassen (Zeile 1 fixieren & fett markieren)
    requests_body = {
        'requests': [
            {
                'updateSheetProperties': {
                    'properties': {
                        'sheetId': 0,
                        'gridProperties': {
                            'frozenRowCount': 1
                        }
                    },
                    'fields': 'gridProperties.frozenRowCount'
                }
            },
            {
                'repeatCell': {
                    'range': {
                        'sheetId': 0,
                        'startRowIndex': 0,
                        'endRowIndex': 1,
                        'startColumnIndex': 0,
                        'endColumnIndex': len(headers)
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'textFormat': {
                                'bold': True
                            },
                            'backgroundColor': {
                                'red': 0.95,
                                'green': 0.95,
                                'blue': 0.95
                            }
                        }
                    },
                    'fields': 'userEnteredFormat(textFormat,backgroundColor)'
                }
            }
        ]
    }
    try:
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=requests_body
        ).execute()
        print("[Sheets] Spaltenüberschriften formatiert (Fett & Zeile fixiert).")
    except Exception as e:
        print(f"[Sheets] Warnung bei Formatierung: {e}")

    return spreadsheet_id


def setup_real_drive_matrix(creds) -> dict:
    """Legt die reale Google-Drive Ordnerstruktur an."""
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)

    print("\n[Google Drive Setup] Erstelle Live-Struktur im Cloud Drive...")
    
    # 1. Stammordner
    root_id = find_or_create_folder(drive_service, "[ VG_Delikatessen_Zentrale ]")

    # 2. Unterordner erstellen
    subfolders = [
        "01_Eingangsarchiv",
        "02_Ausgangsrechnungen",
        "03_System_Steuerung",
        "04_Pruefung_Erforderlich"
    ]
    folder_ids = {}
    for sub in subfolders:
        folder_ids[sub] = find_or_create_folder(drive_service, sub, parent_id=root_id)

    # 3. YYYY/MM_Monat Struktur im Eingangsarchiv
    now = datetime.datetime.now()
    year_str = str(now.year)
    month_str = GERMAN_MONTHS.get(now.month, f"{now.month:02d}_Monat")

    year_folder_id = find_or_create_folder(drive_service, year_str, parent_id=folder_ids["01_Eingangsarchiv"])
    month_folder_id = find_or_create_folder(drive_service, month_str, parent_id=year_folder_id)
    folder_ids["Eingangsarchiv_Aktueller_Monat"] = month_folder_id

    # 4. Zentral-Dashboard initialisieren
    sheet_name = "📊 VG_Zentral_Dashboard"
    spreadsheet_id = find_or_create_dashboard_sheet(drive_service, sheets_service, sheet_name, root_id)

    result = {
        "mode": "real",
        "root_folder_id": root_id,
        "folder_ids": folder_ids,
        "spreadsheet_id": spreadsheet_id,
        "sheet_url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    }

    print("\n--- GOOGLE DRIVE REAL MATRIX SETUP ERFOLGREICH ---")
    print(f"Stammordner ID: {root_id}")
    print(f"Monatspfad: {year_str}/{month_str} (ID: {month_folder_id})")
    print(f"Dashboard Google Sheet URL: {result['sheet_url']}")
    return result


def setup_mock_drive_matrix(base_dir: Path) -> dict:
    """Legt eine lokale Dateistruktur an, um Google Drive lokal zu simulieren."""
    print("\n[Mock Drive Setup] Erstelle lokale Simulations-Struktur...")
    root_name = "[ VG_Delikatessen_Zentrale ]"
    root_path = base_dir / root_name
    root_path.mkdir(parents=True, exist_ok=True)

    # Unterordner
    subfolders = [
        "01_Eingangsarchiv",
        "02_Ausgangsrechnungen",
        "03_System_Steuerung",
        "04_Pruefung_Erforderlich"
    ]
    folder_paths = {}
    for sub in subfolders:
        sub_path = root_path / sub
        sub_path.mkdir(parents=True, exist_ok=True)
        folder_paths[sub] = sub_path

    # Monatspfad
    now = datetime.datetime.now()
    year_str = str(now.year)
    month_str = GERMAN_MONTHS.get(now.month, f"{now.month:02d}_Monat")

    month_path = root_path / "01_Eingangsarchiv" / year_str / month_str
    month_path.mkdir(parents=True, exist_ok=True)
    folder_paths["Eingangsarchiv_Aktueller_Monat"] = month_path

    # Dashboard Mock
    dashboard_file = root_path / "📊 VG_Zentral_Dashboard.csv"
    headers = [
        "Beleg-ID", "Datum", "Lieferant", "Kategorie", "Bruttobetrag (€)", 
        "Nettobetrag (€)", "USt-Satz (%)", "USt-Betrag (€)", "Soll-Konto (SKR03)", 
        "Buchungsstatus", "Zahlungsziel", "Skonto-Frist", "Skonto-Satz (%)", 
        "sevDesk-ID", "Google Drive PDF Link", "Letzte Änderung"
    ]

    if not dashboard_file.exists():
        with open(dashboard_file, "w", encoding="utf-8") as f:
            f.write(",".join(headers) + "\n")
        print(f"[Mock] Dashboard CSV initialisiert unter: {dashboard_file}")
    else:
        print(f"[Mock] Dashboard CSV existiert bereits unter: {dashboard_file}")

    result = {
        "mode": "mock",
        "root_path": str(root_path),
        "folder_paths": {k: str(v) for k, v in folder_paths.items()},
        "dashboard_file": str(dashboard_file)
    }

    print("\n--- MOCK DRIVE MATRIX SETUP ERFOLGREICH ---")
    print(f"Stammordner Pfad: {root_path}")
    print(f"Monatspfad: {year_str}/{month_str}")
    print(f"Dashboard Mock Datei: {dashboard_file}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Drive-Matrix Setup für VG Delikatessen")
    parser.add_argument(
        "--mode", 
        choices=["real", "mock", "auto"], 
        default="auto",
        help="Ausführungsmodus. 'real' erzwingt Google API, 'mock' erzwingt lokale Struktur, 'auto' prüft Credentials."
    )
    parser.add_argument(
        "--credentials", 
        default="credentials.json",
        help="Pfad zur Google OAuth client credentials JSON-Datei (Standard: credentials.json)"
    )
    parser.add_argument(
        "--service-account", 
        default="service_account.json",
        help="Pfad zur Google Service Account JSON-Datei (Standard: service_account.json)"
    )
    args = parser.parse_args()

    mode = args.mode
    creds = None

    if mode == "auto":
        # Prüfen ob credentials oder service account existieren
        if os.path.exists(args.service_account) or os.path.exists(args.credentials):
            mode = "real"
        else:
            print("[Auto-Detect] Keine Google-Credentials gefunden. Fallback auf Mock-Modus.")
            mode = "mock"

    if mode == "real":
        try:
            creds = authenticate_google_apis(args.credentials, args.service_account)
            setup_real_drive_matrix(creds)
        except Exception as e:
            print(f"\n[Error] Verbindung zu Google API fehlgeschlagen: {e}")
            print("Wahlweise können Sie mit '--mode mock' fortfahren, um das System lokal zu testen.")
            sys.exit(1)
    else:
        setup_mock_drive_matrix(MOCK_DRIVE_DIR)


if __name__ == "__main__":
    main()
