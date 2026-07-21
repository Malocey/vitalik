"""Idempotenter Import von sevDesk-Artikeln und -Kontakten in SQLite und RAG-Wiki."""

import csv
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.rag_engine import rag_engine
from src.wiki.wiki_engine import wiki_engine


def _rows(path: Path) -> Iterable[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            yield {
                str(key or "").lstrip("\ufeff").strip().strip('"'): (value or "").strip()
                for key, value in row.items()
            }


def _decimal(value: str):
    if not value:
        return None
    cleaned = value.replace(".", "").replace(",", ".").replace(" ", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _create_schema(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS sevdesk_articles (
            artikelnummer TEXT PRIMARY KEY, name TEXT NOT NULL, einheit TEXT,
            bestand REAL, bestand_aktiviert TEXT, umsatzsteuer REAL,
            einkaufspreis REAL, verkaufspreis REAL, kategorie TEXT,
            beschreibung TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS sevdesk_articles_fts USING fts5(
            artikelnummer, name, kategorie, beschreibung, tokenize='unicode61'
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS sevdesk_contacts (
            kunden_nr TEXT PRIMARY KEY, anrede TEXT, titel TEXT,
            nachname TEXT, vorname TEXT, organisation TEXT, kategorie TEXT,
            iban TEXT, bic TEXT, ust_id TEXT, strasse TEXT, plz TEXT, ort TEXT,
            land TEXT, telefon TEXT, mobil TEXT, email TEXT, webseite TEXT,
            beschreibung TEXT, tags TEXT, debitoren_nr TEXT, kreditoren_nr TEXT,
            steuernummer TEXT, skonto_tage INTEGER, skonto_prozent REAL,
            zahlungsziel_tage INTEGER, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS sevdesk_contacts_fts USING fts5(
            kunden_nr, name, organisation, kategorie, ort, land, tags,
            tokenize='unicode61'
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS sevdesk_sync_state (
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'imported',
            sync_status TEXT NOT NULL DEFAULT 'synced_from_export',
            source_hash TEXT,
            last_synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_error TEXT,
            PRIMARY KEY(entity_type, entity_id)
        )
    """)
    db.commit()


def import_articles(path: Path, db: sqlite3.Connection) -> List[Dict[str, str]]:
    articles = list(_rows(path))
    for row in articles:
        number = row["Artikelnummer"]
        db.execute("""
            INSERT INTO sevdesk_articles (
                artikelnummer, name, einheit, bestand, bestand_aktiviert,
                umsatzsteuer, einkaufspreis, verkaufspreis, kategorie,
                beschreibung, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(artikelnummer) DO UPDATE SET
                name=excluded.name, einheit=excluded.einheit,
                bestand=excluded.bestand,
                bestand_aktiviert=excluded.bestand_aktiviert,
                umsatzsteuer=excluded.umsatzsteuer,
                einkaufspreis=excluded.einkaufspreis,
                verkaufspreis=excluded.verkaufspreis,
                kategorie=excluded.kategorie,
                beschreibung=excluded.beschreibung,
                updated_at=CURRENT_TIMESTAMP
        """, (
            number, row["Name"], row["Einheit"], _decimal(row["Bestand"]),
            row["Bestand aktiviert"], _decimal(row["Umsatzsteuer"]),
            _decimal(row["Einkaufspreis"]), _decimal(row["Verkaufspreis"]),
            row["Kategorie"], row["Beschreibung"],
        ))
        db.execute("DELETE FROM sevdesk_articles_fts WHERE artikelnummer = ?", (number,))
        db.execute(
            "INSERT INTO sevdesk_articles_fts VALUES (?, ?, ?, ?)",
            (number, row["Name"], row["Kategorie"], row["Beschreibung"]),
        )
        db.execute("""
            INSERT INTO sevdesk_sync_state(entity_type, entity_id)
            VALUES ('article', ?)
            ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                sync_status='synced_from_export', last_synced_at=CURRENT_TIMESTAMP,
                last_error=NULL
        """, (number,))
    db.commit()
    return articles


def import_contacts(path: Path, db: sqlite3.Connection) -> List[Dict[str, str]]:
    contacts = list(_rows(path))
    for row in contacts:
        number = row["Kunden-Nr."]
        db.execute("""
            INSERT INTO sevdesk_contacts (
                kunden_nr, anrede, titel, nachname, vorname, organisation,
                kategorie, iban, bic, ust_id, strasse, plz, ort, land,
                telefon, mobil, email, webseite, beschreibung, tags,
                debitoren_nr, kreditoren_nr, steuernummer, skonto_tage,
                skonto_prozent, zahlungsziel_tage, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(kunden_nr) DO UPDATE SET
                anrede=excluded.anrede, titel=excluded.titel,
                nachname=excluded.nachname, vorname=excluded.vorname,
                organisation=excluded.organisation, kategorie=excluded.kategorie,
                iban=excluded.iban, bic=excluded.bic, ust_id=excluded.ust_id,
                strasse=excluded.strasse, plz=excluded.plz, ort=excluded.ort,
                land=excluded.land, telefon=excluded.telefon,
                mobil=excluded.mobil, email=excluded.email,
                webseite=excluded.webseite, beschreibung=excluded.beschreibung,
                tags=excluded.tags, debitoren_nr=excluded.debitoren_nr,
                kreditoren_nr=excluded.kreditoren_nr,
                steuernummer=excluded.steuernummer,
                skonto_tage=excluded.skonto_tage,
                skonto_prozent=excluded.skonto_prozent,
                zahlungsziel_tage=excluded.zahlungsziel_tage,
                updated_at=CURRENT_TIMESTAMP
        """, (
            number, row["Anrede"], row["Titel"], row["Nachname"],
            row["Vorname"], row["Organisation"], row["Kategorie"],
            row["IBAN"], row["BIC"], row["UmSt.-ID"], row["Strasse"],
            row["PLZ"], row["Ort"], row["Land"], row["Telefon"],
            row["Mobil"], row["E-Mail"], row["Webseite"],
            row["Beschreibung"], row["Tags"], row["Debitoren-Nr."],
            row["Kreditoren-Nr."], row["Steuernummer"],
            int(_decimal(row["Skonto Tage"]) or 0),
            _decimal(row["Skonto Prozent"]),
            int(_decimal(row["Zahlungsziel Tage"]) or 0),
        ))
        name = " ".join(filter(None, [row["Vorname"], row["Nachname"]]))
        db.execute("DELETE FROM sevdesk_contacts_fts WHERE kunden_nr = ?", (number,))
        db.execute(
            "INSERT INTO sevdesk_contacts_fts VALUES (?, ?, ?, ?, ?, ?, ?)",
            (number, name, row["Organisation"], row["Kategorie"], row["Ort"], row["Land"], row["Tags"]),
        )
        db.execute("""
            INSERT INTO sevdesk_sync_state(entity_type, entity_id)
            VALUES ('contact', ?)
            ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                sync_status='synced_from_export', last_synced_at=CURRENT_TIMESTAMP,
                last_error=NULL
        """, (number,))
    db.commit()
    return contacts


def write_rag_summaries(articles: List[Dict[str, str]], contacts: List[Dict[str, str]]) -> None:
    article_categories = Counter(row["Kategorie"] for row in articles)
    tax_rates = Counter(row["Umsatzsteuer"] for row in articles)
    article_content = (
        f"## Datenbestand\n\n{len(articles)} Artikel aus sevDesk.\n\n"
        f"## Kategorien\n\n" + "\n".join(f"- {key}: {value}" for key, value in article_categories.items()) +
        f"\n\n## Umsatzsteuersätze\n\n" + "\n".join(f"- {key} %: {value} Artikel" for key, value in tax_rates.items()) +
        "\n\nEinzelne Artikel werden strukturiert über SQLite-FTS gesucht; diese Wiki-Seite enthält bewusst keinen vollständigen Rohdatenexport."
    )
    wiki_engine.create_or_update_page(
        "sevdesk_artikelbestand", "sevDesk Artikelbestand", article_content, "sevdesk"
    )

    contact_categories = Counter(row["Kategorie"] for row in contacts)
    countries = Counter(row["Land"] or "Ohne Land" for row in contacts)
    suppliers = [row for row in contacts if row["Kategorie"].lower() == "lieferant"]
    supplier_lines = [
        f"- {row['Organisation'] or (row['Vorname'] + ' ' + row['Nachname']).strip()} ({row['Ort']}, {row['Land']})"
        for row in suppliers
    ]
    contact_content = (
        f"## Datenbestand\n\n{len(contacts)} Kontakte aus sevDesk.\n\n"
        f"## Kategorien\n\n" + "\n".join(f"- {key}: {value}" for key, value in contact_categories.items()) +
        f"\n\n## Länder\n\n" + "\n".join(f"- {key}: {value}" for key, value in countries.most_common()) +
        f"\n\n## Lieferanten\n\n" + ("\n".join(supplier_lines) or "Keine Lieferanten im Export.") +
        "\n\nSensible Kontakt- und Bankdaten liegen ausschließlich strukturiert in SQLite und nicht im Vektorindex."
    )
    wiki_engine.create_or_update_page(
        "sevdesk_kontaktbestand", "sevDesk Kontaktbestand", contact_content, "sevdesk"
    )


def import_sevdesk_data(article_csv: Path, contact_csv: Path) -> Dict[str, int]:
    with sqlite3.connect(rag_engine.db_path) as db:
        _create_schema(db)
        articles = import_articles(article_csv, db)
        contacts = import_contacts(contact_csv, db)
        unique_articles = db.execute("SELECT count(*) FROM sevdesk_articles").fetchone()[0]
        unique_contacts = db.execute("SELECT count(*) FROM sevdesk_contacts").fetchone()[0]
    write_rag_summaries(articles, contacts)
    return {
        "article_rows": len(articles),
        "articles": unique_articles,
        "article_duplicates": len(articles) - unique_articles,
        "contact_rows": len(contacts),
        "contacts": unique_contacts,
        "contact_duplicates": len(contacts) - unique_contacts,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="sevDesk CSV-Daten in SQLite und RAG importieren")
    parser.add_argument("article_csv", type=Path)
    parser.add_argument("contact_csv", type=Path)
    args = parser.parse_args()
    result = import_sevdesk_data(args.article_csv, args.contact_csv)
    print(
        f"Import erfolgreich: {result['articles']} eindeutige Artikel "
        f"({result['article_duplicates']} doppelte IDs), "
        f"{result['contacts']} eindeutige Kontakte "
        f"({result['contact_duplicates']} doppelte IDs)"
    )
