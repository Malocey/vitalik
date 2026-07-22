import sqlite3
import argparse
import json
import csv
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Set

logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser(description="Evidenzbasierte Bestandsabstimmung")
    parser.add_argument("--db", type=str, default="data/rag_index.db", help="Pfad zur SQLite-Datenbank")
    parser.add_argument("--report", type=str, default=None, help="Verzeichnis für Berichte")
    parser.add_argument("--apply", action="store_true", help="Änderungen in die Datenbank schreiben")
    parser.add_argument("--dry-run", action="store_true", help="Nur simulieren (Standard, wenn --apply nicht gesetzt)")
    return parser.parse_args()

def backup_database(db_path: Path) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
    text = str(text).lower()
    return re.sub(r'[^a-z0-9]', '', text)

def find_entity_by_strong_id(value: str, id_type: str, entities: List[Dict[str, Any]]) -> Optional[str]:
    if not value:
        return None
    val_norm = normalize_text(value)
    for entity in entities:
        ent_val = entity.get(id_type)
        if ent_val and normalize_text(ent_val) == val_norm:
            return entity["entity_id"]
    return None

def extract_strong_ids_from_text(text: str) -> Dict[str, List[str]]:
    ids = {"iban": [], "ust_id": [], "email": []}
    if not text:
        return ids

    ibans = re.findall(r'[A-Z]{2}\d{2}[A-Z0-9]{11,30}', text.replace(' ', '').upper())
    ids["iban"] = list(set(ibans))

    # German USt-ID (DE followed by 9 digits), ATU, CHE
    ust_ids = re.findall(r'(DE|ATU|CHE)[\s\-]?([0-9]{8,11})', text.upper())
    ids["ust_id"] = list(set([u[0] + u[1] for u in ust_ids]))

    emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text)
    ids["email"] = list(set(emails))

    return ids

def reconcile_entities(db_path: str, report_dir: Optional[str] = None, apply: bool = False):
    db_path_obj = Path(db_path)

    if not db_path_obj.exists():
        raise FileNotFoundError(f"Datenbank nicht gefunden: {db_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not report_dir:
        report_dir = f"data/reports/entity_reconciliation/{timestamp}"

    report_path = Path(report_dir)
    report_path.mkdir(parents=True, exist_ok=True)

    if apply:
        backup_database(db_path_obj)

    db = sqlite3.connect(db_path_obj)
    db.row_factory = sqlite3.Row

    summary_data = {"processed": 0, "conflicts": 0, "updated": 0, "unchanged": 0}
    conflicts = []
    audit_log = []

    try:
        cursor = db.cursor()

        # Load entities
        cursor.execute("SELECT * FROM contact_entities")
        entities = [dict(row) for row in cursor.fetchall()]

        # Load contact aliases for weak matching
        cursor.execute("SELECT * FROM contact_aliases")
        aliases = [dict(row) for row in cursor.fetchall()]

        # Process belege
        cursor.execute("SELECT * FROM belege")
        belege = [dict(row) for row in cursor.fetchall()]

        updates = []

        for beleg in belege:
            summary_data["processed"] += 1
            beleg_id = beleg["beleg_id"]

            raw_text = ""
            if beleg.get("raw_text_path") and Path(beleg["raw_text_path"]).exists():
                try:
                    with open(beleg["raw_text_path"], "r", encoding="utf-8") as f:
                        raw_text = f.read()
                except Exception:
                    pass

            if not raw_text:
                try:
                    cursor.execute("SELECT rohtext FROM belege_ocr_fts WHERE beleg_id = ?", (beleg_id,))
                    row = cursor.fetchone()
                    if row:
                        raw_text = row["rohtext"]
                except sqlite3.OperationalError:
                    pass

            found_entities = set()
            conflict_reasons = []

            # 1. Check SevDesk ID from Beleg
            sevdesk_id = beleg.get("sevdesk_kunden_nr")
            if sevdesk_id:
                ent = find_entity_by_strong_id(sevdesk_id, "sevdesk_id", entities)
                if ent:
                    found_entities.add(ent)

            # 2. Extract strong IDs from OCR
            extracted_ids = extract_strong_ids_from_text(raw_text)

            for iban in extracted_ids["iban"]:
                ent = find_entity_by_strong_id(iban, "iban", entities)
                if ent:
                    found_entities.add(ent)

            for ust_id in extracted_ids["ust_id"]:
                ent = find_entity_by_strong_id(ust_id, "tax_id", entities)
                if ent:
                    found_entities.add(ent)

            for email in extracted_ids["email"]:
                ent = find_entity_by_strong_id(email, "email", entities)
                if ent:
                    found_entities.add(ent)

            if len(found_entities) > 1:
                conflict_reasons.append("Unterschiedliche starke Identifikatoren zeigen auf unterschiedliche Kontakte.")

            filename = beleg.get("beleg_link", "") or ""
            supplier_name = beleg.get("lieferant", "") or ""

            weak_entities = set()
            for al in aliases:
                norm_alias = al["normalized_alias"]
                # Must be a substantial word match to avoid over-matching
                if len(norm_alias) > 3 and (norm_alias in normalize_text(filename) or norm_alias in normalize_text(supplier_name) or norm_alias in normalize_text(raw_text)):
                    weak_entities.add(al["entity_id"])


            if len(found_entities) == 1:
                strong_ent = list(found_entities)[0]
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

            if conflict_reasons:
                status = "REVIEW_CONFLICT"
                summary_data["conflicts"] += 1
                conflicts.append({
                    "beleg_id": beleg_id,
                    "reason": " | ".join(conflict_reasons),
                    "lieferant": supplier_name,
                    "raw_text_path": beleg.get("raw_text_path", "")
                })
            else:
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

    with open(report_path / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    with open(report_path / "conflicts.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["beleg_id", "reason", "lieferant", "raw_text_path"])
        writer.writeheader()
        writer.writerows(conflicts)

    with open(report_path / "audit.jsonl", "w", encoding="utf-8") as f:
        for entry in audit_log:
            f.write(json.dumps(entry) + "\n")

    print(f"Abstimmung abgeschlossen. Berichte geschrieben nach: {report_path}")
    print(f"Zusammenfassung: {summary_data}")

if __name__ == "__main__":
    args = parse_args()
    apply = args.apply
    if apply:
        args.dry_run = False
    reconcile_entities(args.db, args.report, apply)
