"""Dublettenfreies, beleggestütztes Kontaktgedächtnis in SQLite."""

import hashlib
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional, Set, List

from src.core.config import DATA_DIR


UNKNOWN_VALUES = {"", "unknown", "unbekannt", "unbekannter lieferant", "fehler"}


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[\w]+", text, flags=re.UNICODE))


def normalize_compact(value: Any) -> str:
    return "".join(character for character in normalize_text(value) if character.isalnum())


class ContactMemory:
    """Lernt Kontakte nur aus sicheren Belegen und führt Evidenz statt Duplikate."""

    def __init__(self, db_path: Path = DATA_DIR / "rag_index.db"):
        self.db_path = Path(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS contact_entities (
                    entity_id TEXT PRIMARY KEY,
                    role TEXT NOT NULL CHECK(role IN ('customer', 'supplier', 'both')),
                    canonical_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    tax_id TEXT,
                    iban TEXT,
                    email TEXT,
                    postal_code TEXT,
                    city TEXT,
                    sevdesk_id TEXT,
                    evidence_count INTEGER NOT NULL DEFAULT 1,
                    confidence REAL NOT NULL,
                    first_document_id TEXT,
                    last_document_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(role, normalized_name, postal_code, city)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_tax_id
                    ON contact_entities(tax_id) WHERE tax_id IS NOT NULL AND tax_id != '';
                CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_iban
                    ON contact_entities(iban) WHERE iban IS NOT NULL AND iban != '';
                CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_email
                    ON contact_entities(email) WHERE email IS NOT NULL AND email != '';
                CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_sevdesk
                    ON contact_entities(sevdesk_id) WHERE sevdesk_id IS NOT NULL AND sevdesk_id != '';
                CREATE TABLE IF NOT EXISTS contact_aliases (
                    role TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    entity_id TEXT NOT NULL REFERENCES contact_entities(entity_id) ON DELETE CASCADE,
                    display_alias TEXT NOT NULL,
                    evidence_count INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(role, normalized_alias)
                );
                CREATE TABLE IF NOT EXISTS contact_evidence (
                    entity_id TEXT NOT NULL REFERENCES contact_entities(entity_id) ON DELETE CASCADE,
                    document_id TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'document',
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(entity_id, document_id)
                );
            """)
            db.commit()

    @staticmethod
    def _candidate_from_document(document: Dict[str, Any], role: str) -> Dict[str, Any]:
        if role == "supplier":
            name = document.get("lieferant") or document.get("supplier")
            prefix = "lieferant"
        else:
            name = (
                document.get("kunde") or document.get("kundenname")
                or document.get("rechnungsempfaenger") or document.get("customer")
            )
            prefix = "kunde"
        return {
            "name": name,
            "tax_id": document.get(f"{prefix}_ust_id") or document.get("ust_id"),
            "iban": document.get(f"{prefix}_iban"),
            "email": document.get(f"{prefix}_email"),
            "postal_code": document.get(f"{prefix}_plz"),
            "city": document.get(f"{prefix}_ort"),
            "sevdesk_id": document.get("sevdesk_kunden_nr") if role == "supplier" else document.get("sevdesk_customer_id"),
        }

    def learn_from_document(self, document: Dict[str, Any], document_id: str) -> Dict[str, Any]:
        """Lernt vorhandene Rollen; unsichere Dokumente verändern die DB nicht."""
        confidence = float(document.get("confidence_score") or 0.0)
        if document.get("validation_status") != "PASSED" or confidence < 0.90:
            return {"status": "SKIPPED_UNSAFE", "entities": []}
        results = []
        for role in ("supplier", "customer"):
            candidate = self._candidate_from_document(document, role)
            if normalize_text(candidate.get("name")) not in UNKNOWN_VALUES:
                result = self.upsert_contact(candidate, role, document_id, confidence)
                results.append(result)
        return {"status": "LEARNED" if results else "NO_CONTACT", "entities": results}

    def upsert_contact(
        self,
        candidate: Dict[str, Any],
        role: str,
        document_id: str,
        confidence: float,
    ) -> Dict[str, Any]:
        if role not in {"customer", "supplier"}:
            raise ValueError(f"Unbekannte Kontaktrolle: {role}")
        name = str(candidate.get("name") or "").strip()
        normalized_name = normalize_text(name)
        if normalized_name in UNKNOWN_VALUES or confidence < 0.90:
            return {"status": "SKIPPED_UNSAFE", "role": role}

        values = {
            "tax_id": normalize_compact(candidate.get("tax_id")) or None,
            "iban": normalize_compact(candidate.get("iban")) or None,
            "email": str(candidate.get("email") or "").strip().casefold() or None,
            "postal_code": normalize_compact(candidate.get("postal_code")) or "",
            "city": normalize_text(candidate.get("city")),
            "sevdesk_id": str(candidate.get("sevdesk_id") or "").strip() or None,
        }
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            matches: Set[str] = set()
            for column in ("tax_id", "iban", "email", "sevdesk_id"):
                if values[column]:
                    matches.update(
                        row[0] for row in db.execute(
                            f"SELECT entity_id FROM contact_entities WHERE {column} = ?",
                            (values[column],),
                        )
                    )
            matches.update(
                row[0] for row in db.execute(
                    """SELECT entity_id FROM contact_entities
                       WHERE role = ? AND normalized_name = ? AND postal_code = ? AND city = ?""",
                    (role, normalized_name, values["postal_code"], values["city"]),
                )
            )
            alias = db.execute(
                "SELECT entity_id FROM contact_aliases WHERE role = ? AND normalized_alias = ?",
                (role, normalized_name),
            ).fetchone()
            if alias:
                matches.add(alias[0])
            if len(matches) > 1:
                db.rollback()
                return {"status": "REVIEW_CONFLICT", "role": role, "matches": sorted(matches)}

            if matches:
                entity_id = next(iter(matches))
                existing = db.execute(
                    "SELECT * FROM contact_entities WHERE entity_id = ?", (entity_id,)
                ).fetchone()
                merged_role = existing["role"] if existing["role"] == role else "both"
                is_new_evidence = db.execute(
                    "SELECT 1 FROM contact_evidence WHERE entity_id = ? AND document_id = ?",
                    (entity_id, document_id),
                ).fetchone() is None
                conflicts = [
                    column for column in ("tax_id", "iban", "email", "sevdesk_id")
                    if existing[column] and values[column] and existing[column] != values[column]
                ]
                if conflicts:
                    db.rollback()
                    return {"status": "REVIEW_CONFLICT", "role": role, "entity_id": entity_id,
                            "conflicts": conflicts}
                db.execute("""
                    UPDATE contact_entities SET
                        role = ?,
                        canonical_name = CASE WHEN length(?) > length(canonical_name) THEN ? ELSE canonical_name END,
                        tax_id = COALESCE(tax_id, ?), iban = COALESCE(iban, ?),
                        email = COALESCE(email, ?), postal_code = CASE WHEN postal_code = '' THEN ? ELSE postal_code END,
                        city = CASE WHEN city = '' THEN ? ELSE city END,
                        sevdesk_id = COALESCE(sevdesk_id, ?), evidence_count = evidence_count + ?,
                        confidence = MAX(confidence, ?), last_document_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE entity_id = ?
                """, (merged_role, name, name, values["tax_id"], values["iban"], values["email"],
                      values["postal_code"], values["city"], values["sevdesk_id"],
                      int(is_new_evidence), confidence, document_id, entity_id))
                status = "MATCHED"
            else:
                identity = "|".join((role, normalized_name, values["postal_code"], values["city"]))
                entity_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
                try:
                    db.execute("""
                        INSERT INTO contact_entities (
                            entity_id, role, canonical_name, normalized_name, tax_id, iban, email,
                            postal_code, city, sevdesk_id, confidence, first_document_id, last_document_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (entity_id, role, name, normalized_name, values["tax_id"], values["iban"],
                          values["email"], values["postal_code"], values["city"], values["sevdesk_id"],
                          confidence, document_id, document_id))
                except sqlite3.IntegrityError:
                    db.rollback()
                    return {"status": "REVIEW_CONFLICT", "role": role, "reason": "unique_identity_collision"}
                status = "CREATED"

            alias_exists = db.execute(
                "SELECT 1 FROM contact_aliases WHERE role = ? AND normalized_alias = ?",
                (role, normalized_name),
            ).fetchone() is not None
            db.execute("""
                INSERT INTO contact_aliases(role, normalized_alias, entity_id, display_alias)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(role, normalized_alias) DO UPDATE SET
                    evidence_count = evidence_count + ?, updated_at = CURRENT_TIMESTAMP
                WHERE entity_id = excluded.entity_id
            """, (role, normalized_name, entity_id, name, int(not alias_exists)))
            db.execute("""
                INSERT OR IGNORE INTO contact_evidence(entity_id, document_id, confidence)
                VALUES (?, ?, ?)
            """, (entity_id, document_id, confidence))
            db.commit()
            return {"status": status, "role": role, "entity_id": entity_id}

    def count_entities(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT count(*) FROM contact_entities").fetchone()[0])

    def match_text(self, document_text: str, role: str = "supplier") -> Optional[Dict[str, Any]]:
        """Findet einen eindeutigen bekannten Alias im Belegtext, ohne Fuzzy-Raten."""
        normalized_document = f" {normalize_text(document_text)} "
        if role not in {"supplier", "customer"}:
            raise ValueError(f"Unbekannte Kontaktrolle: {role}")
        with self._connect() as db:
            rows = db.execute("""
                SELECT a.normalized_alias, e.*
                FROM contact_aliases a
                JOIN contact_entities e USING(entity_id)
                WHERE a.role = ?
                ORDER BY length(a.normalized_alias) DESC
            """, (role,)).fetchall()
        matches = [
            row for row in rows
            if len(row["normalized_alias"]) >= 5
            and f" {row['normalized_alias']} " in normalized_document
        ]
        if not matches:
            return None
        longest = len(matches[0]["normalized_alias"])
        best_ids = {row["entity_id"] for row in matches if len(row["normalized_alias"]) == longest}
        if len(best_ids) != 1:
            return None
        selected = next(row for row in matches if row["entity_id"] in best_ids)
        return {
            "entity_id": selected["entity_id"],
            "name": selected["canonical_name"],
            "role": selected["role"],
            "sevdesk_id": selected["sevdesk_id"],
            "confidence": selected["confidence"],
            "source": "contact_memory",
        }


    def get_all_entities(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("""
                SELECT e.*, COUNT(a.normalized_alias) as alias_count
                FROM contact_entities e
                LEFT JOIN contact_aliases a ON e.entity_id = a.entity_id
                GROUP BY e.entity_id
                ORDER BY e.canonical_name ASC
            """).fetchall()
            return [dict(row) for row in rows]


contact_memory = ContactMemory()
