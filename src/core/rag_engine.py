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
        except Exception as e:
            logger.error(f"[RAG] Fehler bei der Initialisierung von SQLite FTS5: {e}")

    def index_beleg(self, doc_data: Dict[str, Any], beleg_id: str):
        """Indiziert einen verarbeiteten Beleg in der SQLite FTS5 Tabelle."""
        if not doc_data:
            return

        lieferant = doc_data.get("lieferant", "")
        datum = doc_data.get("datum", "")
        betrag = str(doc_data.get("brutto", ""))
        rohtext = doc_data.get("raw_text", "")

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO belege_fts (beleg_id, lieferant, datum, betrag, rohtext)
                    VALUES (?, ?, ?, ?, ?)
                """, (beleg_id, lieferant, datum, betrag, rohtext))
                conn.commit()
                logger.info(f"[RAG] Beleg {beleg_id} erfolgreich in FTS5 indiziert.")
        except Exception as e:
            logger.error(f"[RAG] Fehler beim Indizieren von Beleg {beleg_id} in FTS5: {e}")

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
                match_query = ' OR '.join([f'"{word}"*' for word in clean_query.split()])

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
        except Exception as e:
            logger.error(f"[RAG] Fehler bei FTS5 Volltextsuche: {e}")

        return results

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
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self.documents, f, ensure_ascii=False, indent=2)

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

        # 1. FTS5 Suche für schnelle Beleg-Treffer
        if use_fts and (not category_filter or category_filter == "beleg"):
            fts_results = self.search_fts(query, top_k)
            results.extend(fts_results)

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

        # Optional: Ergebnisse mischen/sortieren, aber hier belassen wir es einfach bei der kombinierten Liste
        # FTS-Ergebnisse sind oft präziser bei exakten Suchen, daher stehen sie vorne
        return results[:max(top_k, len(results))] # Begrenzung auf alle gefundenen, wenn nicht explizit gefiltert

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
