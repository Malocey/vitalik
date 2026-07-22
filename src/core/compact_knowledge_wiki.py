"""Reversible Migration vom Beleg-Wiki zum verdichteten Entitäts-Wiki."""

import argparse
import json
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from config import DATA_DIR, WIKI_DIR
from src.core.rag_engine import rag_engine
from src.wiki.wiki_engine import wiki_engine


def load_belege(db_path: Path) -> List[Dict[str, Any]]:
    with sqlite3.connect(str(db_path)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(
            "SELECT * FROM belege WHERE beleg_id NOT LIKE 'TEST-%' ORDER BY beleg_id"
        )]


def analyze(rows: List[Dict[str, Any]], wiki_dir: Path) -> Dict[str, Any]:
    suppliers = defaultdict(list)
    unresolved = []
    duplicate_keys = Counter()
    for row in rows:
        name = str(row.get("lieferant") or "Unbekannter Lieferant").strip()
        normalized = "".join(character for character in name.casefold() if character.isalnum())
        if normalized in {"", "unknown", "unbekannt", "unbekannterlieferant", "bank", "dublittemd5", "fehler"}:
            unresolved.append(row["beleg_id"])
            continue
        key = str(row.get("contact_entity_id") or name.casefold())
        suppliers[key].append(row["beleg_id"])
        invoice_key = (
            key, str(row.get("rechnungsnummer") or "").strip().casefold(),
            str(row.get("datum") or ""), row.get("brutto"),
        )
        if invoice_key[1]:
            duplicate_keys[invoice_key] += 1
    expected_names = {
        f"beleg_{''.join(character if character.isalnum() or character in '_-' else '_' for character in str(row['beleg_id'])).strip('_')}.md"
        for row in rows
    }
    old_pages = [wiki_dir / name for name in expected_names if (wiki_dir / name).is_file()]
    return {
        "mode": "dry-run",
        "belege": len(rows),
        "old_beleg_pages": len(old_pages),
        "canonical_supplier_pages": len(suppliers),
        "unresolved_documents": len(unresolved),
        "review_pages": 1 if unresolved else 0,
        "pages_saved": max(0, len(old_pages) - len(suppliers) - (1 if unresolved else 0)),
        "possible_business_duplicates": sum(count - 1 for count in duplicate_keys.values() if count > 1),
        "largest_supplier_groups": sorted(
            ({"entity": key, "documents": len(ids)} for key, ids in suppliers.items()),
            key=lambda item: item["documents"], reverse=True,
        )[:20],
    }


def _backup(db_path: Path, wiki_dir: Path, backup_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_root / stamp
    target.mkdir(parents=True, exist_ok=False)
    if wiki_dir.exists():
        shutil.copytree(wiki_dir, target / "wiki")
    with sqlite3.connect(str(db_path)) as source, sqlite3.connect(str(target / "rag_index.db")) as dest:
        source.backup(dest)
    return target


def apply_compaction(
    db_path: Path, wiki_dir: Path, backup_root: Path,
    wiki_manager=None, rag_manager=None,
) -> Dict[str, Any]:
    wiki_manager = wiki_manager or wiki_engine
    rag_manager = rag_manager or rag_engine
    if wiki_manager.wiki_dir.resolve() != wiki_dir.resolve():
        raise ValueError("Wiki-Manager und Zielverzeichnis stimmen nicht überein")
    rows = load_belege(db_path)
    report = analyze(rows, wiki_dir)
    backup = _backup(db_path, wiki_dir, backup_root)
    archive = wiki_dir / "archive" / "belege"
    archive.mkdir(parents=True, exist_ok=True)
    archived = 0
    expected_names = {
        f"beleg_{''.join(character if character.isalnum() or character in '_-' else '_' for character in str(row['beleg_id'])).strip('_')}.md"
        for row in rows
    }
    for page in sorted(wiki_dir / name for name in expected_names if (wiki_dir / name).is_file()):
        destination = archive / page.name
        if destination.exists():
            destination = archive / f"{page.stem}-{datetime.now().strftime('%H%M%S%f')}.md"
        shutil.move(str(page), str(destination))
        archived += 1

    # Alte Einzelbeleg-Vektoren dürfen die neue Entitätssuche nicht überstimmen.
    rag_manager.documents = [
        item for item in rag_manager.documents
        if not str(item.get("doc_id", "")).startswith("wiki_beleg_")
    ]
    rag_manager.save_index()

    with sqlite3.connect(str(db_path)) as db:
        generated_pages = set()
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for row in rows:
            doc = dict(row)
            doc["validation_status"] = doc.get("status")
            doc["skr03_konto"] = doc.get("skr_konto")
            page = wiki_manager.update_contact_page(doc, doc["beleg_id"], synchronize=False)
            generated_pages.add(page)
            db.execute(
                "UPDATE belege SET wiki_path = ?, updated_at = CURRENT_TIMESTAMP WHERE beleg_id = ?",
                (str(page), doc["beleg_id"]),
            )
            if {"belege_fts", "belege_ocr_fts"}.issubset(tables):
                summary = str(doc.get("summary") or (
                    f"Beleg {doc['beleg_id']} von {doc.get('lieferant', '')}, "
                    f"Datum {doc.get('datum', '')}, Brutto {doc.get('brutto', '')} EUR, "
                    f"Rechnungsnummer {doc.get('rechnungsnummer', '')}, "
                    f"Warengruppe {doc.get('warengruppe', '')}."
                ))
                raw_path = Path(str(doc.get("raw_text_path") or ""))
                raw_text = raw_path.read_text(encoding="utf-8", errors="replace") if raw_path.is_file() else summary
                db.execute("DELETE FROM belege_fts WHERE beleg_id = ?", (doc["beleg_id"],))
                db.commit()
                db.execute(
                    "INSERT INTO belege_fts (beleg_id, lieferant, datum, betrag, rohtext) VALUES (?, ?, ?, ?, ?)",
                    (doc["beleg_id"], doc.get("lieferant", ""), doc.get("datum", ""),
                     str(doc.get("brutto", "")), summary),
                )
                db.commit()
                db.execute("DELETE FROM belege_ocr_fts WHERE beleg_id = ?", (doc["beleg_id"],))
                db.commit()
                db.execute(
                    "INSERT INTO belege_ocr_fts (beleg_id, rohtext) VALUES (?, ?)",
                    (doc["beleg_id"], raw_text),
                )
                db.commit()
        db.commit()
    for page in sorted(generated_pages):
        text = page.read_text(encoding="utf-8")
        title = next((line[2:] for line in text.splitlines() if line.startswith("# ")), page.stem)
        category = "wiki_prüfung" if "entity_type: review_queue" in text else "wiki_lieferant"
        rag_manager.index_document(
            doc_id=f"wiki_compacted_{page.stem}", title=title, content=text,
            source=str(page), category=category,
        )
    wiki_manager.rebuild_index_page()
    wiki_manager.log_event(
        "COMPACT", f"{len(rows)} Belege in {len(generated_pages)} aktive Wissensseiten verdichtet."
    )
    report.update({"mode": "apply", "backup": str(backup), "archived_pages": archived})
    report_path = backup / "compaction_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Migration nach automatischer Sicherung ausführen")
    parser.add_argument("--output", type=Path, help="Dry-Run-Bericht als JSON speichern")
    args = parser.parse_args()
    rows = load_belege(rag_engine.db_path)
    if args.apply:
        report = apply_compaction(
            rag_engine.db_path, wiki_engine.wiki_dir, DATA_DIR / "backups" / "wiki_compaction"
        )
    else:
        report = analyze(rows, wiki_engine.wiki_dir)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
