import json
import uuid
from typing import Optional
from fastmcp import FastMCP
from src.core.rag_engine import rag_engine

# Initialisiere den FastMCP Server für das KI Langzeitgedächtnis
mcp = FastMCP("VG_Memory", description="KI Langzeitgedächtnis (RAG) für Suche und Speicherung von Gedanken.")

@mcp.tool()
def search_memory(query: str, category_filter: str = "") -> str:
    """
    Durchsucht das Langzeitgedächtnis (RAG & Wiki) nach relevanten Informationen.
    query: Der Suchbegriff oder die Frage.
    category_filter: Optional (z.B. "beleg", "wiki_lieferant", "gedanke"). Leer lassen für alle Kategorien.
    """
    try:
        results = rag_engine.search(
            query=query,
            top_k=5,
            category_filter=category_filter if category_filter else None
        )

        if not results:
            return "Keine relevanten Erinnerungen gefunden."

        formatted_results = []
        for r in results:
            formatted_results.append(
                f"--- {r.get('title', 'Ohne Titel')} (Kategorie: {r.get('category', 'Unbekannt')}) ---\n"
                f"{r.get('content', '')}\n"
            )

        return "\n".join(formatted_results)
    except Exception as e:
        return f"Fehler bei der Speichersuche: {e}"

@mcp.tool()
def memorize_thought(title: str, content: str, category: str = "gedanke") -> str:
    """
    Speichert einen neuen Gedanken, eine Zusammenfassung oder wichtige Fakten dauerhaft im Langzeitgedächtnis der KI.
    title: Kurzer, prägnanter Titel für die Erinnerung.
    content: Der detaillierte Inhalt, der gespeichert werden soll.
    category: Die Kategorie (Standard: "gedanke", kann auch "kundennotiz", "rezept" etc. sein).
    """
    try:
        # Generiere eine eindeutige ID für den neuen Gedanken
        doc_id = f"memory_{uuid.uuid4().hex[:8]}"

        # Nutze die RAGEngine, um das Dokument zu indizieren und als Vektor zu speichern
        rag_engine.add_document(
            doc_id=doc_id,
            title=title,
            content=content,
            source="mcp_agent",
            category=category
        )

        return json.dumps({
            "status": "success",
            "message": "Erinnerung erfolgreich im Langzeitgedächtnis verankert.",
            "doc_id": doc_id,
            "title": title
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Fehler beim Speichern der Erinnerung: {e}"
        })

if __name__ == "__main__":
    # Startet den Server (stdio-basiert, perfekt für Claude Desktop & co)
    mcp.run()
