"""
Lokales RAG-System (Retrieval-Augmented Generation) für VG Delikatessen.
Liest Testdaten, Drive-Exporte, Mails & Notizen ein, erzeugt Embeddings und ermöglicht Vektorsuche.
"""

import json
import math
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import VECTORSTORE_DIR, TESTDATA_DIR
from src.core.local_llm_client import LocalLLMClient, default_llm_client


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
        self.documents: List[Dict[str, Any]] = []
        self.load_index()

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

    def search(self, query: str, top_k: int = 3, category_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Führt eine semantische Ähnlichkeitssuche für eine Anforderung/Frage aus.
        """
        if not self.documents:
            return []

        query_embedding = self.llm_client.generate_embedding(query)
        results = []

        for doc in self.documents:
            if category_filter and doc.get("category") != category_filter:
                continue

            sim = cosine_similarity(query_embedding, doc.get("embedding", []))
            results.append({
                "doc_id": doc.get("doc_id"),
                "title": doc.get("title"),
                "content": doc.get("content"),
                "source": doc.get("source"),
                "category": doc.get("category"),
                "score": round(sim, 4)
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

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
