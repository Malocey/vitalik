import sqlite3
import argparse
import json
import csv
import logging
import re
import unicodedata
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Set

logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser(description="Evidenzbasierte Bestandsabstimmung")
    parser.add_argument("--db", type=str, default="data/rag_index.db", help="Pfad zur SQLite-Datenbank")
    parser.add_argument("--report", type=str, default=None, help="Verzeichnis für Berichte")
    parser.add_argument("--backup-dir", type=str, default=None, help="Verzeichnis für das Backup (wenn --apply genutzt wird)")

    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--apply", action="store_true", help="Änderungen in die Datenbank schreiben")
    group.add_argument("--dry-run", action="store_true", help="Nur simulieren (Standard, wenn --apply nicht gesetzt)")

    return parser.parse_args()

def backup_database(db_path: Path, backup_dir_base: Optional[str] = None) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if backup_dir_base:
        backup_dir = Path(backup_dir_base) / timestamp
    else:
        backup_dir = Path(f"data/backups/entity_reconciliation/{timestamp}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / "rag_index.db"

    try:
        source = sqlite3.connect(db_path)
        dest = sqlite3.connect(backup_path)
        with source:
            source.backup(dest)
        dest.close()
        source.close()

        check_conn = sqlite3.connect(backup_path)
        cursor = check_conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        check_conn.close()

        if result[0] != "ok":
            raise RuntimeError(f"Backup integrity check failed: {result[0]}")

        print(f"Backup erfolgreich erstellt: {backup_path}")
    except Exception as e:
        logger.error(f"Fehler beim Erstellen des Backups: {e}")
        raise RuntimeError(f"Backup fehlgeschlagen: {e}")

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text).casefold())
    return "".join(
        character for character in text
        if not unicodedata.combining(character) and character.isalnum()
    )

def find_entities_by_strong_id(value: str, id_type: str, entities: List[Dict[str, Any]]) -> Set[str]:
    found = set()
    if not value:
        return found
    val_norm = normalize_text(value)
    for entity in entities:
        ent_val = entity.get(id_type)
        if ent_val and normalize_text(ent_val) == val_norm:
            found.add(entity["entity_id"])
    return found

def extract_strong_ids_from_text(text: str) -> Dict[str, List[str]]:
    ids = {"iban": [], "ust_id": [], "email": []}
    if not text:
        return ids

    ibans = re.findall(r'[A-Z]{2}\d{2}[A-Z0-9]{11,30}', text.replace(' ', '').upper())
    ids["iban"] = list(set(ibans))

    ust_ids = re.findall(r'(DE|ATU|CHE)[\s\-]?([0-9]{8,11})', text.upper())
    ids["ust_id"] = list(set([u[0] + u[1] for u in ust_ids]))

    emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text)
    ids["email"] = list(set(emails))

    return ids

def atomic_write(filepath: Path, content: str, is_jsonl: bool = False, is_csv: bool = False, fieldnames: list = None, data: Any = None):
    tmp_path = filepath.with_suffix(filepath.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8", newline="" if is_csv else None) as f:
        if is_jsonl:
            for entry in data:
                f.write(json.dumps(entry) + "\n")
        elif is_csv:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
        else:
            json.dump(data, f, indent=2)

    os.replace(tmp_path, filepath)

def reconcile_entities(db_path: str, report_dir: Optional[str] = None, apply: bool = False, backup_dir: Optional[str] = None):
    db_path_obj = Path(db_path)

    if not db_path_obj.exists():
        raise FileNotFoundError(f"Datenbank nicht gefunden: {db_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not report_dir:
        report_dir = f"data/reports/entity_reconciliation/{timestamp}"

    report_path = Path(report_dir)
    report_path.mkdir(parents=True, exist_ok=True)

    if apply:
        backup_database(db_path_obj, backup_dir)

    db = sqlite3.connect(db_path_obj)
    db.row_factory = sqlite3.Row

    summary_data = {"processed": 0, "conflicts": 0, "updated": 0, "unchanged": 0}
    conflicts = []
    audit_log = []

    try:
        cursor = db.cursor()

        cursor.execute("SELECT * FROM contact_entities")
        entities = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM contact_aliases")
        aliases = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM belege")
        belege = [dict(row) for row in cursor.fetchall()]

        updates = []

        for beleg in belege:
            summary_data["processed"] += 1
            beleg_id = beleg["beleg_id"]
            belegtyp = beleg.get("belegtyp") or ""

            # Determine likely role of the document to avoid mapping supplier to customer
            is_supplier_doc = belegtyp.lower() in ["rechnung", "ausgabe", "bon", "quittung"]
            is_customer_doc = belegtyp.lower() in ["einnahme", "ausgangsrechnung"]

            raw_text = ""
            file_unreadable = False
            if beleg.get("raw_text_path"):
                p = Path(beleg["raw_text_path"])
                if not p.exists():
                    file_unreadable = True
                else:
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            raw_text = f.read()
                    except Exception:
                        file_unreadable = True

            if not raw_text and not file_unreadable:
                try:
                    cursor.execute("SELECT rohtext FROM belege_ocr_fts WHERE beleg_id = ?", (beleg_id,))
                    row = cursor.fetchone()
                    if row:
                        raw_text = row["rohtext"]
                except sqlite3.OperationalError:
                    pass

            found_entities = set()
            conflict_reasons = []

            if file_unreadable:
                conflict_reasons.append("SOURCE_UNREADABLE")

            sevdesk_id = beleg.get("sevdesk_kunden_nr")
            if sevdesk_id:
                found_entities.update(find_entities_by_strong_id(sevdesk_id, "sevdesk_id", entities))

            extracted_ids = extract_strong_ids_from_text(raw_text)

            for iban in extracted_ids["iban"]:
                found_entities.update(find_entities_by_strong_id(iban, "iban", entities))

            for ust_id in extracted_ids["ust_id"]:
                found_entities.update(find_entities_by_strong_id(ust_id, "tax_id", entities))

            for email in extracted_ids["email"]:
                found_entities.update(find_entities_by_strong_id(email, "email", entities))

            # Check for conflict among strong IDs
            if len(found_entities) > 1:
                conflict_reasons.append("Unterschiedliche starke Identifikatoren zeigen auf unterschiedliche Kontakte.")

            filename = beleg.get("beleg_link", "") or ""
            supplier_name = beleg.get("lieferant", "") or ""

            weak_entities = set()
            for al in aliases:
                norm_alias = normalize_text(al["normalized_alias"])
                if len(norm_alias) > 3 and (norm_alias in normalize_text(filename) or norm_alias in normalize_text(supplier_name) or norm_alias in normalize_text(raw_text)):
                    weak_entities.add(al["entity_id"])

            if len(found_entities) == 1:
                strong_ent = list(found_entities)[0]

                # Check entity role mismatch
                ent_record = next((e for e in entities if e["entity_id"] == strong_ent), None)
                if ent_record:
                    if is_supplier_doc and ent_record["role"] == "customer":
                        conflict_reasons.append(f"Kontakt {strong_ent} hat Rolle 'customer', Beleg ist aber Lieferantenbeleg.")
                    elif is_customer_doc and ent_record["role"] == "supplier":
                        conflict_reasons.append(f"Kontakt {strong_ent} hat Rolle 'supplier', Beleg ist aber Kundenbeleg.")

                other_weak_entities = weak_entities - {strong_ent}
                if other_weak_entities:
                    conflict_reasons.append(f"Starker Identifikator zeigt auf {strong_ent}, aber schwache Evidenz (OCR/Name/Datei) deutet auf andere Kontakte: {other_weak_entities}.")

            current_entity_id = beleg.get("contact_entity_id")

            if current_entity_id and found_entities and current_entity_id not in found_entities:
                 conflict_reasons.append(f"Bestehende contact_entity_id ({current_entity_id}) widerspricht neu gefundener starker Identität {found_entities}.")

            if not found_entities and len(weak_entities) > 1:
                conflict_reasons.append("Mehrere plausible Kontakte anhand schwacher Evidenz, keiner kann eindeutig ausgeschlossen werden.")

            status = "UNCHANGED"
            proposed_entity = None

            if file_unreadable:
                status = "SOURCE_UNREADABLE"

            if conflict_reasons:
                if status != "SOURCE_UNREADABLE":
                    status = "REVIEW_CONFLICT"
                summary_data["conflicts"] += 1
                conflicts.append({
                    "beleg_id": beleg_id,
                    "reason": " | ".join(conflict_reasons),
                    "lieferant": supplier_name,
                    "raw_text_path": beleg.get("raw_text_path", "")
                })
            elif not file_unreadable:
                if len(found_entities) == 1:
                    proposed_entity = list(found_entities)[0]
                    if proposed_entity != current_entity_id:
                        status = "UPDATED"
                        summary_data["updated"] += 1
                        updates.append((proposed_entity, beleg_id))
                    else:
                        summary_data["unchanged"] += 1
                else:
                    summary_data["unchanged"] += 1

            audit_log.append({
                "beleg_id": beleg_id,
                "status": status,
                "current_entity": current_entity_id,
                "proposed_entity": proposed_entity,
                "conflict_reason": " | ".join(conflict_reasons) if conflict_reasons else None
            })

        if apply and updates:
            db.execute("BEGIN TRANSACTION")
            try:
                db.executemany("UPDATE belege SET contact_entity_id = ? WHERE beleg_id = ?", updates)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Fehler beim Update: {e}")
                raise

    finally:
        db.close()

    atomic_write(report_path / "summary.json", "", data=summary_data)
    atomic_write(report_path / "conflicts.csv", "", is_csv=True, fieldnames=["beleg_id", "reason", "lieferant", "raw_text_path"], data=conflicts)
    atomic_write(report_path / "audit.jsonl", "", is_jsonl=True, data=audit_log)

    print(f"Abstimmung abgeschlossen. Berichte geschrieben nach: {report_path}")
    print(f"Zusammenfassung: {summary_data}")

if __name__ == "__main__":
    args = parse_args()

    # If explicitly passed --apply, dry_run should be false
    # if --dry-run is passed, apply is implicitly false, handled by mutually exclusive group

    apply = args.apply
    reconcile_entities(args.db, args.report, apply, args.backup_dir)
