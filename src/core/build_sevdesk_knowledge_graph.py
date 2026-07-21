"""Erzeugt stabile Wiki-/RAG-Nodes aus den strukturierten sevDesk-Stammdaten."""

import os
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.rag_engine import rag_engine
from src.wiki.wiki_engine import wiki_engine


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value)).strip("_") or "unknown"


def _write(path: Path, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_graph() -> dict:
    with sqlite3.connect(rag_engine.db_path) as db:
        db.row_factory = sqlite3.Row
        contacts = db.execute("SELECT * FROM sevdesk_contacts ORDER BY kategorie, kunden_nr").fetchall()
        articles = db.execute("SELECT * FROM sevdesk_articles ORDER BY kategorie, artikelnummer").fetchall()

    base = wiki_engine.wiki_dir / "entities"
    contact_dir = base / "contacts"
    article_dir = base / "articles"
    category_dir = base / "categories"
    rag_documents = []
    contact_groups = defaultdict(list)
    article_groups = defaultdict(list)

    # Frühere Einzel-Artikel-Nodes entfernen; Artikel gehören ausschließlich
    # als strukturierte Einträge in ihre jeweilige Artikelart.
    for old_article_page in article_dir.glob("article_*.md"):
        old_article_page.unlink()

    for row in contacts:
        node_id = f"contact_{_slug(row['kunden_nr'])}"
        group_id = f"contact_type_{_slug(row['kategorie'].lower())}"
        display_name = row["organisation"] or " ".join(filter(None, [row["vorname"], row["nachname"]]))
        content = (
            f"# {display_name}\n*Kategorie: sevdesk_{row['kategorie'].lower()}*\n\n"
            f"- **Node-ID:** {node_id}\n"
            f"- **sevDesk-Kontakt-ID:** {row['kunden_nr']}\n"
            f"- **Typ:** {row['kategorie']}\n"
            f"- **Organisation:** {row['organisation']}\n"
            f"- **Ort/Land:** {row['ort']}, {row['land']}\n"
            f"- **Debitor:** {row['debitoren_nr']}\n"
            f"- **Kreditor:** {row['kreditoren_nr']}\n"
            f"- **Zahlungsziel:** {row['zahlungsziel_tage']} Tage\n"
            f"- **Skonto:** {row['skonto_prozent']} % in {row['skonto_tage']} Tagen\n\n"
            f"## Beziehungen\n\n- [[{group_id}|{row['kategorie']}]]\n\n"
            f"## Synchronisierung\n\nQuelle: sevDesk, Status: aus CSV importiert."
        )
        path = contact_dir / f"{node_id}.md"
        _write(path, content)
        contact_groups[row["kategorie"]].append((node_id, display_name))
        rag_documents.append({"doc_id": node_id, "title": display_name, "content": content, "source": str(path), "category": f"sevdesk_{row['kategorie'].lower()}"})

    for row in articles:
        article_groups[row["kategorie"]].append(row)

    root_links = []
    for group, nodes in contact_groups.items():
        node_id = f"contact_type_{_slug(group.lower())}"
        content = f"# sevDesk {group}\n*Kategorie: sevdesk_kontaktart*\n\n## Kontakte\n\n" + "\n".join(f"- [[{child_id}|{label}]]" for child_id, label in nodes)
        path = category_dir / f"{node_id}.md"
        _write(path, content)
        rag_documents.append({"doc_id": node_id, "title": f"sevDesk {group}", "content": content, "source": str(path), "category": "sevdesk_kontaktart"})
        root_links.append((node_id, f"Kontakte: {group}"))

    for group, group_articles in article_groups.items():
        node_id = f"article_category_{_slug(group.lower())}"
        article_lines = []
        for row in group_articles:
            description = re.sub(r"\s+", " ", row["beschreibung"] or "").strip()
            article_lines.append(
                f"- **{row['artikelnummer']} – {row['name']}** | "
                f"Einheit: {row['einheit']} | USt: {row['umsatzsteuer']} % | "
                f"EK: {row['einkaufspreis']} EUR | VK: {row['verkaufspreis']} EUR"
                + (f" | {description}" if description else "")
            )
        content = (
            f"# Artikelart {group}\n*Kategorie: sevdesk_artikelart*\n\n"
            f"- **Anzahl Artikel:** {len(group_articles)}\n"
            f"- **Quelle:** sevDesk\n"
            f"- **Sync-Status:** aus CSV importiert\n\n"
            f"## Artikel\n\n" + "\n".join(article_lines)
        )
        path = category_dir / f"{node_id}.md"
        _write(path, content)
        rag_documents.append({"doc_id": node_id, "title": f"Artikelart {group}", "content": content, "source": str(path), "category": "sevdesk_artikelart"})
        root_links.append((node_id, f"Artikelart: {group}"))

    root_content = "# sevDesk Wissensgraph\n*Kategorie: sevdesk*\n\n## Einstiegspunkte\n\n" + "\n".join(f"- [[{node_id}|{label}]]" for node_id, label in root_links)
    root_path = wiki_engine.wiki_dir / "sevdesk_wissensgraph.md"
    _write(root_path, root_content)
    rag_documents.append({"doc_id": "sevdesk_wissensgraph", "title": "sevDesk Wissensgraph", "content": root_content, "source": str(root_path), "category": "sevdesk"})

    rag_engine.documents = [
        document for document in rag_engine.documents
        if not (
            str(document.get("doc_id", "")).startswith("article_")
            and not str(document.get("doc_id", "")).startswith("article_category_")
        )
    ]
    rag_engine.index_documents(rag_documents)
    wiki_engine.rebuild_index_page()
    return {"contacts": len(contacts), "articles": len(articles), "nodes": len(rag_documents)}


if __name__ == "__main__":
    result = build_graph()
    print(f"Graph erstellt: {result['nodes']} Nodes ({result['contacts']} Kontakte, {result['articles']} Artikel)")
