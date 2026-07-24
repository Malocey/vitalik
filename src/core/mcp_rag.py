import json
import uuid
from typing import Optional
from fastmcp import FastMCP
from src.core.rag_engine import rag_engine
from src.wiki.wiki_engine import wiki_engine

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

@mcp.tool()
def list_wiki_pages(sub_dir: str = "") -> str:
    """
    Listet alle strukturierten Wiki-Seiten auf.
    sub_dir: Optional (z.B. "Kunden" oder "Rezepte").
    Verwende dies, um zu sehen, welche strukturierten Dokumentationen bereits existieren.
    """
    try:
        pages = wiki_engine.list_pages(sub_dir)
        return json.dumps({"status": "success", "pages": pages}, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@mcp.tool()
def read_wiki_page(slug: str) -> str:
    """
    Liest den exakten Inhalt einer strukturierten Wiki-Seite im Markdown-Format.
    slug: Der Bezeichner der Seite (z.B. "kunden/mueller" oder "prozesse/rechnungsstellung").
    """
    try:
        content = wiki_engine.read_page(slug)
        if content:
            return json.dumps({"status": "success", "content": content})
        return json.dumps({"status": "error", "message": "Seite nicht gefunden."})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@mcp.tool()
def write_wiki_page(slug: str, title: str, category: str, content: str) -> str:
    """
    Erstellt oder überschreibt eine dauerhafte, strukturierte Wiki-Seite im Markdown-Format.

    WICHTIGE BEST PRACTICES (WIKI_AI_GUIDELINES):
    1. content MUSS reines Markdown sein. Tabellen (|, -) sind erlaubt. KEIN HTML (wie <div>, <span>).
    2. Der content MUSS ohne YAML-Frontmatter übergeben werden (die Engine generiert das Frontmatter automatisch aus slug, title, category).
    3. Nutze Obsidian-Links [[Slugs]] innerhalb des contents, um andere Wiki-Seiten zu verlinken!

    slug: Eindeutiger Pfad (z.B. "kunden/meier_catering", kleingeschrieben).
    title: Menschlicher Titel (z.B. "Meier Catering").
    category: Art des Dokuments (z.B. "kunde", "rezept", "prozess").
    content: Der Markdown-Text (ohne Frontmatter).
    """
    try:
        # Die wiki_engine.create_or_update_page generiert das Frontmatter automatisch und
        # stößt den RAG-Index sofort an!
        saved_path = wiki_engine.create_or_update_page(
            slug=slug,
            title=title,
            content=content,
            category=category
        )
        return json.dumps({
            "status": "success",
            "message": f"Wiki-Seite erfolgreich unter {saved_path} erstellt und im RAG-Index verankert."
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

if __name__ == "__main__":
    # Startet den Server (stdio-basiert, perfekt für Claude Desktop & co)
    mcp.run()
