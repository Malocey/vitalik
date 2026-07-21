"""Read-only-Neuklassifikation bestehender OCR-Belege ohne Datenmutation."""

import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.rag_engine import rag_engine


BANK_MARKERS = {
    "Commerzbank": ("commerzbank", "cobadeff"),
    "Deutsche Bank": ("deutsche bank", "deutde"),
    "Sparkasse": ("sparkasse",),
    "Volksbank/Raiffeisenbank": ("volksbank", "raiffeisenbank"),
}


def classify_document(text: str) -> dict:
    normalized = re.sub(r"\s+", " ", text.casefold())
    bank = next(
        (name for name, markers in BANK_MARKERS.items() if any(marker in normalized for marker in markers)),
        None,
    )
    statement_signals = {
        "kontoauszug": "kontoauszug" in normalized,
        "auszug_nr": bool(re.search(r"auszug[\s-]*nr", normalized)),
        "kontonummer": "kontonummer" in normalized,
        "buchungsdatum": "buchungsdatum" in normalized,
        "lasten_gunsten": "zu ihren lasten" in normalized and "zu ihren gunsten" in normalized,
        "bank": bank is not None,
    }
    statement_score = sum(statement_signals.values())
    is_statement = statement_score >= 3 and statement_signals["bank"]

    statement_date = None
    date_match = re.search(
        r"kontoauszug\s+vom\s+(\d{2})\.(\d{2})\.(\d{4})",
        normalized,
    )
    if date_match:
        day, month, year = date_match.groups()
        statement_date = f"{year}-{month}-{day}"

    return {
        "document_type": "Kontoauszug" if is_statement else "Unverändert/weitere Prüfung",
        "issuer": bank if is_statement else None,
        "statement_date": statement_date,
        "statement_score": statement_score,
        "signals": [name for name, matched in statement_signals.items() if matched],
    }


def run_audit(report_path: Path) -> dict:
    with sqlite3.connect(rag_engine.db_path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT beleg_id, lieferant, datum, brutto, status,
                   beleg_link, raw_text_path
            FROM belege
            WHERE beleg_id NOT LIKE 'TEST-%'
            ORDER BY beleg_id
        """).fetchall()

    findings = []
    for row in rows:
        raw_path = Path(row["raw_text_path"] or "")
        text = raw_path.read_text(encoding="utf-8", errors="replace") if raw_path.is_file() else ""
        classification = classify_document(text)
        if classification["document_type"] == "Kontoauszug":
            findings.append({**dict(row), **classification})

    report_path.parent.mkdir(parents=True, exist_ok=True)
    issuer_counts = Counter(item["issuer"] for item in findings)
    lines = [
        "# Read-only Audit: bestehende Dokumentklassifikation",
        "",
        f"Erstellt: {datetime.now().isoformat(timespec='seconds')}",
        f"Geprüfte Belege: {len(rows)}",
        f"Als Kontoauszug erkannt: {len(findings)}",
        "Daten verändert: nein",
        "",
        "## Erkannte Bankaussteller",
        "",
    ]
    lines.extend(f"- {issuer}: {count}" for issuer, count in issuer_counts.most_common())
    lines.extend(["", "## Abweichungen", ""])
    for item in findings:
        lines.extend([
            f"### {item['beleg_id']}",
            "",
            f"- Bisheriger Lieferant: {item['lieferant']}",
            f"- Vorgeschlagener Aussteller: {item['issuer']}",
            f"- Vorgeschlagener Dokumenttyp: {item['document_type']}",
            f"- Kontoauszugsdatum: {item['statement_date'] or 'nicht eindeutig'}",
            f"- Bisheriger Betrag: {item['brutto']} EUR (bei Kontoauszügen nicht als Rechnungsbrutto verwenden)",
            f"- Erkennungssignale: {', '.join(item['signals'])}",
            f"- Original: {item['beleg_link']}",
            "",
        ])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return {"checked": len(rows), "statements": len(findings), "report": str(report_path)}


if __name__ == "__main__":
    target = PROJECT_ROOT / "data" / "reports" / "beleg_reclassification_audit.md"
    result = run_audit(target)
    print(
        f"Audit abgeschlossen: {result['checked']} Belege geprüft, "
        f"{result['statements']} Kontoauszüge erkannt. Bericht: {result['report']}"
    )
