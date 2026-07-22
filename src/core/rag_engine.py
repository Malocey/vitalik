"""
Lokales RAG-System (Retrieval-Augmented Generation) für VG Delikatessen.
Liest Testdaten, Drive-Exporte, Mails & Notizen ein, erzeugt Embeddings und ermöglicht Vektorsuche.
"""

import json
import math
import os
import re
import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import VECTORSTORE_DIR, TESTDATA_DIR, DATA_DIR
from src.core.local_llm_client import LocalLLMClient, default_llm_client

logger = logging.getLogger("RAGEngine")


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


class RAGEngine:
    def __init__(self, llm_client: Optional[LocalLLMClient] = None):
        self.llm_client = llm_client or default_llm_client
        self.index_file = VECTORSTORE_DIR / "index.json"
        self.db_path = DATA_DIR / "rag_index.db"
        self.documents: List[Dict[str, Any]] = []
        self._init_sqlite_db()
        self.load_index()

    def _init_sqlite_db(self):
        """Initialisiert die SQLite FTS5 Datenbank."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS belege_fts USING fts5(
                        beleg_id, lieferant, datum, betrag, rohtext,
                        tokenize='unicode61'
                    );
                """)
                conn.commit()
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS belege_ocr_fts USING fts5(
                        beleg_id UNINDEXED, rohtext, tokenize='unicode61'
                    );
                """)
                conn.commit()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS belege (
                        beleg_id TEXT PRIMARY KEY,
                        lieferant TEXT, datum TEXT, rechnungsnummer TEXT,
                        netto REAL, steuer REAL, brutto REAL, ust_satz REAL,
                        warengruppe TEXT, skr_konto TEXT, status TEXT,
                        belegtyp TEXT, confidence_score REAL, md5_hash TEXT,
                        rag_read_verified INTEGER DEFAULT 0,
                        beleg_link TEXT, wiki_path TEXT, raw_text_path TEXT,
                        summary TEXT, sevdesk_kunden_nr TEXT, contact_entity_id TEXT,
                        kreditoren_nr TEXT, zahlungsziel_tage INTEGER,
                        skonto_tage INTEGER, skonto_prozent REAL,
                        lieferant_match_source TEXT, steuer_match_source TEXT,
                        sevdesk_artikel_matches TEXT,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
                existing_columns = {
                    row[1] for row in cursor.execute("PRAGMA table_info(belege)").fetchall()
                }
                additional_columns = {
                    "sevdesk_kunden_nr": "TEXT", "contact_entity_id": "TEXT",
                    "kreditoren_nr": "TEXT",
                    "zahlungsziel_tage": "INTEGER", "skonto_tage": "INTEGER",
                    "skonto_prozent": "REAL", "lieferant_match_source": "TEXT",
                    "steuer_match_source": "TEXT", "sevdesk_artikel_matches": "TEXT",
                    "belegtyp": "TEXT", "confidence_score": "REAL",
                    "md5_hash": "TEXT", "rag_read_verified": "INTEGER DEFAULT 0",
                }
                for column, column_type in additional_columns.items():
                    if column not in existing_columns:
                        cursor.execute(f"ALTER TABLE belege ADD COLUMN {column} {column_type}")
                        conn.commit()
        except sqlite3.Error as e:
            message = f"[RAG ERROR] Fehler bei der Initialisierung von SQLite FTS5: {e}"
            print(message)
            logger.exception(message)
            raise

    def index_beleg(self, doc_data: Dict[str, Any], beleg_id: str):
        """Indiziert einen verarbeiteten Beleg in der SQLite FTS5 Tabelle."""
        doc_data = doc_data or {}

        lieferant = doc_data.get("lieferant", "")
        datum = doc_data.get("datum", "")
        betrag = str(doc_data.get("brutto", ""))
        rohtext = doc_data.get("raw_text")
        if not rohtext or not str(rohtext).strip():
            rohtext = (
                f"Lieferant: {lieferant}, Datum: {datum}, Betrag: {betrag} EUR, "
                f"Beleg-ID: {beleg_id}"
            )

        summary = doc_data.get("summary") or (
            f"Beleg {beleg_id} von {lieferant}, Datum {datum}, "
            f"Brutto {betrag} EUR, Rechnungsnummer "
            f"{doc_data.get('rechnungsnummer', '')}, Warengruppe "
            f"{doc_data.get('warengruppe', '')}, Status "
            f"{doc_data.get('validation_status', '')}."
        )

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO belege (
                        beleg_id, lieferant, datum, rechnungsnummer, netto,
                        steuer, brutto, ust_satz, warengruppe, skr_konto,
                        status, beleg_link, wiki_path, raw_text_path, summary,
                        belegtyp, confidence_score, md5_hash, rag_read_verified,
                        sevdesk_kunden_nr, contact_entity_id, kreditoren_nr, zahlungsziel_tage,
                        skonto_tage, skonto_prozent, lieferant_match_source,
                        steuer_match_source, sevdesk_artikel_matches,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(beleg_id) DO UPDATE SET
                        lieferant=excluded.lieferant, datum=excluded.datum,
                        rechnungsnummer=excluded.rechnungsnummer,
                        netto=excluded.netto, steuer=excluded.steuer,
                        brutto=excluded.brutto, ust_satz=excluded.ust_satz,
                        warengruppe=excluded.warengruppe,
                        skr_konto=excluded.skr_konto, status=excluded.status,
                        beleg_link=excluded.beleg_link,
                        wiki_path=excluded.wiki_path,
                        raw_text_path=excluded.raw_text_path,
                        summary=excluded.summary,
                        belegtyp=excluded.belegtyp,
                        confidence_score=excluded.confidence_score,
                        md5_hash=excluded.md5_hash,
                        rag_read_verified=excluded.rag_read_verified,
                        sevdesk_kunden_nr=excluded.sevdesk_kunden_nr,
                        contact_entity_id=excluded.contact_entity_id,
                        kreditoren_nr=excluded.kreditoren_nr,
                        zahlungsziel_tage=excluded.zahlungsziel_tage,
                        skonto_tage=excluded.skonto_tage,
                        skonto_prozent=excluded.skonto_prozent,
                        lieferant_match_source=excluded.lieferant_match_source,
                        steuer_match_source=excluded.steuer_match_source,
                        sevdesk_artikel_matches=excluded.sevdesk_artikel_matches,
                        updated_at=CURRENT_TIMESTAMP
                """, (
                    beleg_id, lieferant, datum, doc_data.get("rechnungsnummer", ""),
                    doc_data.get("netto"), doc_data.get("steuer"),
                    doc_data.get("brutto"), doc_data.get("steuersatz_prozent"),
                    doc_data.get("warengruppe", ""), doc_data.get("skr03_konto", ""),
                    doc_data.get("validation_status", ""), doc_data.get("beleg_link", ""),
                    doc_data.get("wiki_path", ""), doc_data.get("raw_text_path", ""), summary,
                    doc_data.get("belegtyp", ""), doc_data.get("confidence_score"),
                    doc_data.get("md5_hash", ""), int(bool(doc_data.get("rag_read_verified"))),
                    doc_data.get("sevdesk_kunden_nr"), doc_data.get("contact_entity_id"),
                    doc_data.get("kreditoren_nr"),
                    doc_data.get("zahlungsziel_tage"), doc_data.get("skonto_tage"),
                    doc_data.get("skonto_prozent"), doc_data.get("lieferant_match_source"),
                    doc_data.get("steuer_match_source"),
                    json.dumps(doc_data.get("sevdesk_artikel_matches", []), ensure_ascii=False),
                ))
                conn.commit()
                cursor.execute("DELETE FROM belege_fts WHERE beleg_id = ?", (beleg_id,))
                conn.commit()
                cursor.execute("""
                    INSERT INTO belege_fts (beleg_id, lieferant, datum, betrag, rohtext)
                    VALUES (?, ?, ?, ?, ?)
                """, (beleg_id, lieferant, datum, betrag, summary))
                conn.commit()
                cursor.execute("DELETE FROM belege_ocr_fts WHERE beleg_id = ?", (beleg_id,))
                conn.commit()
                cursor.execute(
                    "INSERT INTO belege_ocr_fts (beleg_id, rohtext) VALUES (?, ?)",
                    (beleg_id, str(rohtext)),
                )
                conn.commit()
                logger.info(f"[RAG] Beleg {beleg_id} erfolgreich in FTS5 indiziert.")
        except sqlite3.Error as e:
            message = f"[RAG ERROR] Fehler beim Indizieren von Beleg {beleg_id} in FTS5: {e}"
            print(message)
            logger.exception(message)
            raise

    def verify_beleg_persistence(self, beleg_id: str) -> Dict[str, Any]:
        """Prüft SQLite, FTS5, Wiki-Quelle und Vektorindex nach erneutem Öffnen."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT wiki_path, raw_text_path FROM belege WHERE beleg_id = ?",
                    (beleg_id,),
                ).fetchone()
                fts_count = conn.execute(
                    "SELECT count(*) FROM belege_fts WHERE beleg_id = ?",
                    (beleg_id,),
                ).fetchone()[0]
            wiki_exists = bool(row and row[0] and Path(row[0]).is_file())
            raw_exists = bool(row and row[1] and Path(row[1]).is_file())
            vector_exists = any(
                row and row[0] and document.get("source") == row[0]
                for document in self.documents
            )
            result = {
                "sqlite": row is not None, "fts5": fts_count > 0,
                "wiki": wiki_exists, "raw_source": raw_exists,
                "vector": vector_exists,
            }
            result["ok"] = all(result.values())
            return result
        except sqlite3.Error as e:
            message = f"[RAG ERROR] Persistenzprüfung für {beleg_id} fehlgeschlagen: {e}"
            print(message)
            logger.exception(message)
            raise

    def find_beleg_by_md5(self, md5_hash: str) -> Optional[Dict[str, Any]]:
        """Findet einen bereits vollständig gespeicherten Teilbeleg für Resume/Deduplizierung."""
        if not md5_hash:
            return None
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM belege WHERE md5_hash = ? ORDER BY updated_at LIMIT 1",
                    (md5_hash,),
                ).fetchone()
            if not row:
                return None
            result = dict(row)
            verification = self.verify_beleg_persistence(result["beleg_id"])
            if not verification["ok"]:
                return None
            result["persistence_verification"] = verification
            result["persistence_verified"] = True
            result["validation_status"] = result.get("status")
            result["steuersatz_prozent"] = result.get("ust_satz")
            return result
        except sqlite3.Error as e:
            message = f"[RAG ERROR] MD5-Lookup fehlgeschlagen: {e}"
            print(message)
            logger.exception(message)
            raise

    def search_fts(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Führt eine Volltextsuche über die SQLite FTS5 Tabelle aus."""
        results = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Bereite die Query für den MATCH-Operator vor (z.B. Wörter aneinanderreihen)
                # Entferne Sonderzeichen für FTS5
                clean_query = re.sub(r'[^\w\s]', ' ', query).strip()
                if not clean_query:
                    return results

                # Erstelle eine MATCH Query: Jedes Wort wird als Prefix gesucht
                stopwords = {"seite", "rechnung", "datum", "betrag", "lieferant", "eur", "und", "der", "die", "das"}
                words = []
                for word in clean_query.split():
                    lowered = word.casefold()
                    if len(lowered) >= 3 and lowered not in stopwords and lowered not in words:
                        words.append(lowered)
                    if len(words) >= 20:
                        break
                if not words:
                    return results
                match_query = ' OR '.join([f'"{word}"*' for word in words])

                cursor.execute("""
                    SELECT beleg_id, lieferant, datum, betrag, rohtext, rank
                    FROM belege_fts
                    WHERE belege_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (match_query, top_k))

                for row in cursor.fetchall():
                    results.append({
                        "doc_id": row["beleg_id"],
                        "title": f"Beleg {row['beleg_id']} ({row['datum']}) - {row['lieferant']}",
                        "content": row["rohtext"],
                        "source": "fts5",
                        "category": "beleg",
                        "score": row["rank"] # Beachte: SQLite rank ist negativ (kleiner ist besser), aber hier nur zur Info
                    })
                # Vollständiger OCR-Text dient nur als Fallback. Damit dominieren
                # wiederholte Fußzeilen und AGB nicht die präzisen Belegdaten.
                if len(results) < top_k:
                    known = {item["doc_id"] for item in results}
                    cursor.execute("""
                        SELECT o.beleg_id, o.rohtext, o.rank,
                               b.lieferant, b.datum, b.brutto
                        FROM belege_ocr_fts AS o
                        LEFT JOIN belege AS b USING (beleg_id)
                        WHERE belege_ocr_fts MATCH ?
                        ORDER BY o.rank LIMIT ?
                    """, (match_query, top_k * 2))
                    for row in cursor.fetchall():
                        if row["beleg_id"] in known:
                            continue
                        results.append({
                            "doc_id": row["beleg_id"],
                            "title": f"Beleg {row['beleg_id']} ({row['datum']}) - {row['lieferant']}",
                            "content": row["rohtext"], "source": "ocr_fallback",
                            "category": "beleg", "score": row["rank"],
                        })
                        if len(results) >= top_k:
                            break
        except sqlite3.Error as e:
            message = f"[RAG ERROR] Fehler bei FTS5 Volltextsuche: {e}"
            print(message)
            logger.exception(message)
            raise

        return results

    def search_sevdesk(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Durchsucht kompakte sevDesk-Artikel- und Kontaktdaten per FTS5."""
        clean_query = re.sub(r'[^\w\s]', ' ', query).strip()
        if not clean_query:
            return []
        match_query = ' OR '.join(f'"{word}"*' for word in clean_query.split())
        results: List[Dict[str, Any]] = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if "sevdesk_articles_fts" in tables:
                    rows = conn.execute("""
                        SELECT f.artikelnummer, f.name, f.kategorie, f.beschreibung,
                               a.einheit, a.umsatzsteuer, a.einkaufspreis,
                               a.verkaufspreis, f.rank
                        FROM sevdesk_articles_fts AS f
                        JOIN sevdesk_articles AS a USING (artikelnummer)
                        WHERE sevdesk_articles_fts MATCH ? ORDER BY rank LIMIT ?
                    """, (match_query, top_k)).fetchall()
                    results.extend({
                        "doc_id": f"sevdesk_article_{row['artikelnummer']}",
                        "title": f"Artikel {row['artikelnummer']} – {row['name']}",
                        "content": (
                            f"Kategorie: {row['kategorie']}; Einheit: {row['einheit']}; "
                            f"USt: {row['umsatzsteuer']} %; Einkaufspreis: "
                            f"{row['einkaufspreis']} EUR; Verkaufspreis: "
                            f"{row['verkaufspreis']} EUR. {row['beschreibung']}"
                        ),
                        "source": "sevdesk_articles_fts", "category": "sevdesk_artikel",
                        "score": row["rank"],
                    } for row in rows)
                if "sevdesk_contacts_fts" in tables:
                    rows = conn.execute("""
                        SELECT f.kunden_nr, f.name, f.organisation, f.kategorie,
                               f.ort, f.land, c.zahlungsziel_tage,
                               c.skonto_tage, c.skonto_prozent, f.rank
                        FROM sevdesk_contacts_fts AS f
                        JOIN sevdesk_contacts AS c USING (kunden_nr)
                        WHERE sevdesk_contacts_fts MATCH ? ORDER BY rank LIMIT ?
                    """, (match_query, top_k)).fetchall()
                    results.extend({
                        "doc_id": f"sevdesk_contact_{row['kunden_nr']}",
                        "title": f"Kontakt {row['kunden_nr']} – {row['organisation'] or row['name']}",
                        "content": (
                            f"{row['kategorie']}, {row['ort']}, {row['land']}; "
                            f"Zahlungsziel: {row['zahlungsziel_tage']} Tage; "
                            f"Skonto: {row['skonto_prozent']} % in "
                            f"{row['skonto_tage']} Tagen"
                        ),
                        "source": "sevdesk_contacts_fts", "category": "sevdesk_kontakt",
                        "score": row["rank"],
                    } for row in rows)
        except sqlite3.Error as e:
            message = f"[RAG ERROR] Fehler bei sevDesk-FTS5-Suche: {e}"
            print(message)
            logger.exception(message)
            raise
        return sorted(results, key=lambda item: item["score"])[:top_k]

    def match_sevdesk_assignment(self, document_text: str, article_limit: int = 12) -> Dict[str, Any]:
        """Ermittelt direkte Lieferanten- und Artikelmatches für die Belegzuordnung."""
        normalized_text = re.sub(r"\s+", " ", document_text.casefold())
        assignment: Dict[str, Any] = {"supplier": None, "articles": []}
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                tables = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "sevdesk_contacts" in tables:
                    suppliers = conn.execute("""
                        SELECT kunden_nr, organisation, vorname, nachname,
                               kreditoren_nr, zahlungsziel_tage,
                               skonto_tage, skonto_prozent
                        FROM sevdesk_contacts
                        WHERE lower(kategorie) = 'lieferant'
                    """).fetchall()
                    candidates = []
                    for row in suppliers:
                        display_name = row["organisation"] or " ".join(
                            filter(None, [row["vorname"], row["nachname"]])
                        )
                        normalized_name = re.sub(r"\s+", " ", display_name.casefold()).strip()
                        name_tokens = [
                            token for token in re.findall(r"\w{4,}", normalized_name)
                            if token not in {"gmbh", "mbh", "kg", "ohg", "firma"}
                        ]
                        token_hits = sum(token in normalized_text for token in name_tokens)
                        fuzzy_match = bool(name_tokens) and token_hits >= min(2, len(name_tokens)) and token_hits / len(name_tokens) >= 0.7
                        if len(normalized_name) >= 4 and (normalized_name in normalized_text or fuzzy_match):
                            candidates.append((len(normalized_name), row, display_name))
                    if candidates:
                        _, row, display_name = max(candidates, key=lambda item: item[0])
                        assignment["supplier"] = {
                            "kunden_nr": row["kunden_nr"], "name": display_name,
                            "kreditoren_nr": row["kreditoren_nr"],
                            "zahlungsziel_tage": row["zahlungsziel_tage"],
                            "skonto_tage": row["skonto_tage"],
                            "skonto_prozent": row["skonto_prozent"],
                        }
                if "sevdesk_articles" in tables:
                    articles = conn.execute("""
                        SELECT artikelnummer, name, kategorie, einheit,
                               umsatzsteuer, einkaufspreis
                        FROM sevdesk_articles
                    """).fetchall()
                    matches = []
                    for row in articles:
                        normalized_name = re.sub(r"\s+", " ", row["name"].casefold()).strip()
                        if len(normalized_name) >= 5 and normalized_name in normalized_text:
                            matches.append({key: row[key] for key in row.keys()})
                            if len(matches) >= article_limit:
                                break
                    assignment["articles"] = matches
        except sqlite3.Error as e:
            message = f"[RAG ERROR] Fehler beim sevDesk-Zuordnungsmatching: {e}"
            print(message)
            logger.exception(message)
            raise
        return assignment

    def load_index(self):
        """Lädt den bestehenden Vektorindex aus der JSON-Datei."""
        if self.index_file.exists():
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    self.documents = json.load(f)
            except Exception as e:
                print(f"[RAG] Fehler beim Laden des Vektorindex: {e}")
                self.documents = []
        else:
            self.documents = []

    def save_index(self):
        """Speichert den Vektorindex lokal."""
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self.documents, f, ensure_ascii=False, indent=2)

    def index_document(
        self,
        doc_id: str,
        title: str,
        content: str,
        source: str = "general",
        category: str = "kontext",
    ):
        """Erstellt oder ersetzt ein Dokument im persistenten Vektorindex."""
        self.index_documents([{
            "doc_id": doc_id, "title": title, "content": content,
            "source": source, "category": category,
        }])

    def index_documents(self, documents: List[Dict[str, str]]) -> None:
        """Indiziert mehrere Dokumente effizient und persistiert nur einmal."""
        doc_ids = {document["doc_id"] for document in documents}
        chunk_prefixes = tuple(f"{doc_id}_chunk_" for doc_id in doc_ids)
        self.documents = [
            document for document in self.documents
            if document.get("doc_id") not in doc_ids
            and not str(document.get("id", "")).startswith(chunk_prefixes)
        ]
        for document in documents:
            for idx, chunk in enumerate(self._chunk_text(document["content"])):
                self.documents.append({
                    "id": f"{document['doc_id']}_chunk_{idx}",
                    "doc_id": document["doc_id"],
                    "title": document["title"],
                    "content": chunk,
                    "source": document.get("source", "general"),
                    "category": document.get("category", "kontext"),
                    "embedding": self.llm_client.generate_embedding(chunk),
                })
        self.save_index()

    def add_document(self, doc_id: str, title: str, content: str, source: str = "general", category: str = "kontext"):
        """
        Teilt ein Dokument in Abschnitte auf, generiert Embeddings und fügt sie dem Index hinzu.
        """
        chunks = self._chunk_text(content)
        for idx, chunk in enumerate(chunks):
            embedding = self.llm_client.generate_embedding(chunk)
            entry = {
                "id": f"{doc_id}_chunk_{idx}",
                "doc_id": doc_id,
                "title": title,
                "content": chunk,
                "source": source,
                "category": category,
                "embedding": embedding
            }
            self.documents.append(entry)
        self.save_index()

    def _chunk_text(self, text: str, chunk_size: int = 400, overlap: int = 50) -> List[str]:
        """Spaltet Text in sinnvolle Abschnitte auf."""
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = ""

        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
            if len(current_chunk) + len(p) <= chunk_size:
                current_chunk += ("\n\n" if current_chunk else "") + p
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = p

        if current_chunk:
            chunks.append(current_chunk)

        return chunks if chunks else [text]

    def search(self, query: str, top_k: int = 3, category_filter: Optional[str] = None, use_fts: bool = True) -> List[Dict[str, Any]]:
        """
        Führt eine semantische Ähnlichkeitssuche für eine Anforderung/Frage aus.
        Wenn use_fts True ist, werden auch SQLite FTS5 Ergebnisse gesucht.
        """
        results = []
        query_words = {
            word for word in re.findall(r"\w+", query.casefold()) if len(word) >= 3
        }

        # Verdichtete Wiki-Hubseiten zuerst: Bei einer Lieferantensuche ist eine
        # gepflegte Entitätsseite hilfreicher als fünf fast identische Belege.
        for doc in self.documents:
            if category_filter and doc.get("category") != category_filter:
                continue
            if not str(doc.get("category", "")).startswith("wiki_"):
                continue
            title_words = set(re.findall(r"\w+", str(doc.get("title", "")).casefold()))
            if query_words and query_words.issubset(title_words):
                results.append({
                    "doc_id": doc.get("doc_id"), "title": doc.get("title"),
                    "content": doc.get("content"), "source": doc.get("source"),
                    "category": doc.get("category"), "score": 1.0,
                })

        # 1. FTS5 Suche für schnelle Beleg-Treffer
        if use_fts and (not category_filter or category_filter == "beleg"):
            fts_results = self.search_fts(query, top_k)
            results.extend(fts_results)

        if use_fts and (not category_filter or category_filter.startswith("sevdesk")):
            results.extend(self.search_sevdesk(query, top_k))

        # 2. Vektor-Suche (falls Dokumente vorhanden)
        if self.documents:
            query_embedding = self.llm_client.generate_embedding(query)
            vec_results = []

            for doc in self.documents:
                if category_filter and doc.get("category") != category_filter:
                    continue

                sim = cosine_similarity(query_embedding, doc.get("embedding", []))
                # Nur relevante Treffer behalten
                if sim > 0.3:
                    vec_results.append({
                        "doc_id": doc.get("doc_id"),
                        "title": doc.get("title"),
                        "content": doc.get("content"),
                        "source": doc.get("source"),
                        "category": doc.get("category"),
                        "score": round(sim, 4)
                    })

            vec_results.sort(key=lambda x: x["score"], reverse=True)
            results.extend(vec_results[:top_k])

        unique = []
        seen = set()
        for result in results:
            key = result.get("doc_id") or result.get("source")
            if key in seen:
                continue
            seen.add(key)
            unique.append(result)
            if len(unique) >= top_k:
                break
        return unique

    def ingest_directory(self, dir_path: Path):
        """Indexiert alle Text-, Markdown- und JSON-Dateien in einem Verzeichnis."""
        if not dir_path.exists():
            return

        count = 0
        for file in dir_path.rglob("*"):
            if file.is_file() and file.suffix.lower() in [".txt", ".md", ".json"]:
                try:
                    content = file.read_text(encoding="utf-8")
                    self.add_document(
                        doc_id=file.name,
                        title=file.stem.replace("_", " ").title(),
                        content=content,
                        source=str(file),
                        category="testdata"
                    )
                    count += 1
                except Exception as e:
                    print(f"[RAG] Fehler beim Indexieren von {file.name}: {e}")
        
        print(f"[RAG] {count} Dateien aus {dir_path} erfolgreich indexiert.")


# Globale RAG-Instanz
rag_engine = RAGEngine()
