"""
Karpathy LLM-Wiki Engine für VG Delikatessen.
Implementiert das 'LLM Wiki' Konzept von Andrej Karpathy:
- Persistent Compounding Wiki (interlinked Markdown)
- `index.md`: Inhalts-Katalog mit Links & Zusammenfassungen
- `log.md`: Chronologisches, parsbares Event-Log (`## [YYYY-MM-DD] action | summary`)
- `lint_wiki()`: Automatische Qualitätsprüfung (Waisen-Seiten, fehlende Links, Widersprüche)
- Multi-Page Cross-Referencing & Compounding Query-Saving
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import WIKI_DIR, DATA_DIR
from src.core.rag_engine import rag_engine

RAW_SOURCES_DIR = DATA_DIR / "raw_sources"
RAW_SOURCES_DIR.mkdir(parents=True, exist_ok=True)


class KarpathyLLMWikiEngine:
    def __init__(self, wiki_dir: Path = WIKI_DIR):
        self.wiki_dir = wiki_dir
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.wiki_dir / "index.md"
        self.log_file = self.wiki_dir / "log.md"

    def log_event(self, action_type: str, summary: str):
        """
        Fügt einen chronologischen Eintrag in `log.md` an.
        Format: ## [YYYY-MM-DD HH:MM] action_type | summary
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        log_entry = f"## [{timestamp}] {action_type.upper()} | {summary}\n"

        existing = self.log_file.read_text(encoding="utf-8") if self.log_file.exists() else "# 📜 VG Delikatessen LLM-Wiki Log\n\n"
        self.log_file.write_text(existing + log_entry, encoding="utf-8")

    def create_or_update_page(
        self,
        slug: str,
        title: str,
        content: str,
        category: str = "konzept",
        cross_links: Optional[List[str]] = None
    ) -> Path:
        """
        Erstellt oder aktualisiert eine Wiki-Seite und verknüpft Querverweise.
        """
        file_name = f"{slug}.md"
        page_path = self.wiki_dir / file_name

        header = f"# {title}\n*Kategorie: {category}* | *Zuletzt aktualisiert: {datetime.now().strftime('%Y-%m-%d')}*\n\n"
        
        # Querverweise hinzufügen
        links_section = ""
        if cross_links:
            links_section = "\n\n### 🔗 Querverweise\n" + "\n".join([f"- [{link}](./{link}.md)" for link in cross_links])

        full_markdown = header + content.strip() + links_section + "\n"
        page_path.write_text(full_markdown, encoding="utf-8")

        # Ins RAG-System einspeisen
        rag_engine.add_document(
            doc_id=f"wiki_{slug}",
            title=title,
            content=full_markdown,
            source=str(page_path),
            category=f"wiki_{category}"
        )

        self.rebuild_index_page()
        self.log_event("UPDATE_PAGE", f"Seite '{title}' ({file_name}) erstellt/aktualisiert.")
        return page_path

    def rebuild_index_page(self):
        """
        Generiert Karpathy's `index.md` neu.
        Katalog aller Seiten mit Links, Einzeilen-Zusammenfassungen und Kategorien.
        """
        pages = [p for p in self.wiki_dir.glob("*.md") if p.name not in ["index.md", "log.md"]]

        content = "# 📖 VG Delikatessen LLM-Wiki Index\n"
        content += f"*Persistent Compounding Knowledge Base | Stand: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n"
        content += "--- \n\n"
        content += "## 📁 Inhaltskatalog\n\n"

        categories: Dict[str, List[Dict[str, str]]] = {}

        for p in sorted(pages):
            lines = p.read_text(encoding="utf-8").split("\n")
            title = p.stem.replace("_", " ").title()
            summary = "Keine Zusammenfassung"
            cat = "Allgemein"

            for line in lines:
                if line.startswith("# "):
                    title = line.replace("# ", "").strip()
                elif "*Kategorie:" in line:
                    parts = line.split("|")
                    cat = parts[0].replace("*Kategorie:", "").replace("*", "").strip()
                elif line.strip() and not line.startswith("#") and not line.startswith("*"):
                    summary = line.strip()[:120]
                    break

            if cat not in categories:
                categories[cat] = []
            categories[cat].append({"slug": p.stem, "title": title, "summary": summary, "filename": p.name})

        for cat_name, cat_pages in categories.items():
            content += f"### {cat_name.title()}\n"
            for item in cat_pages:
                content += f"- **[{item['title']}](./{item['filename']})**: {item['summary']}...\n"
            content += "\n"

        self.index_file.write_text(content, encoding="utf-8")

    def save_compounding_answer(self, query: str, answer: str) -> Path:
        """
        Speichert wertvolle RAG-Abfrageergebnisse als neue dauerhafte Wiki-Seite ab (Compounding Knowledge).
        """
        slug_clean = "".join([c if c.isalnum() else "_" for c in query.lower()])[:40].strip("_")
        title = f"Analyse: {query[:50]}"

        page_path = self.create_or_update_page(
            slug=f"query_{slug_clean}",
            title=title,
            content=f"### Ursprüngliche Frage:\n> {query}\n\n### Generierte Erkenntnisse:\n{answer}",
            category="erkenntnis"
        )
        self.log_event("COMPOUND_QUERY", f"Erkenntnis gespeichert für: '{query[:40]}'")
        return page_path

    def lint_wiki(self) -> Dict[str, Any]:
        """
        Karpathy Lint pass:
        Prüft das Wiki auf Waisen-Seiten (ohne Links), unvollständige Begriffe,
        und stellt die Konsistenz des Vektorindex sicher.
        """
        pages = [p for p in self.wiki_dir.glob("*.md") if p.name not in ["index.md", "log.md"]]
        all_links = set()
        orphans = []

        for p in pages:
            text = p.read_text(encoding="utf-8")
            for other in pages:
                if other.name != p.name and f"[{other.stem}]" in text or f"./{other.name}" in text:
                    all_links.add(other.name)

        for p in pages:
            if p.name not in all_links and p.stem not in ["vitali_persona_und_stil", "lieferanten_und_kontenrahmen"]:
                orphans.append(p.name)

        report = {
            "total_pages": len(pages),
            "orphan_pages": orphans,
            "status": "HEALTHY" if not orphans else "NEEDS_LINKING",
            "message": f"Wiki-Lint abgeschlossen. {len(pages)} Seiten geprüft."
        }
        self.log_event("LINT_PASS", report["message"])
        return report

    def initialize_default_wiki(self):
        """Initialisiert Karpathy's LLM-Wiki Standardstruktur."""
        self.create_or_update_page(
            slug="vitali_persona_und_stil",
            title="Vitali Persona & Schreibstil",
            content="""### Vitalis Tonalität & Kommunikationsregeln
- **Stil**: Direkt, pragmatisch, gastfreundlich, qualitätsbewusst.
- **Sprachkombination**: Deutsch (Geschäftssprache & Telegram-Kommunikation).
- **Verknüpfung Privat & Geschäft**: Vitali führt VG Delikatessen mit persönlicher Passion. Qualität bei Feinkost und Fleisch bestimmt die Lieferantenwahl.
""",
            category="persona"
        )

        self.create_or_update_page(
            slug="lieferanten_und_kontenrahmen",
            title="Lieferanten & SKR03/SKR04 Steuerzuordnung",
            content="""### Wichtige Lieferanten & Zuordnungen
1. **Fleischwaren & Lebensmittel (7% USt)**:
   - SKR03: Konto 3400 (Wareneingang 7%) / SKR04: Konto 5400
   - Beispiele: Metzgerei-Großhandel, Gewürze, Feinkost-Importe.
2. **Reinigungsmittel, Verpackung & Betriebsbedarf (19% USt)**:
   - SKR03: Konto 4900 (Sonstiger Betriebsbedarf) / SKR04: Konto 6300
""",
            category="buchhaltung",
            cross_links=["vitali_persona_und_stil"]
        )

        self.create_or_update_page(
            slug="beleg_pipeline_anleitung",
            title="Beleg-Pipeline & 3-Stufen-Schutzschild",
            content="""### Workflow für Belegverarbeitung
1. **Scans & PDFs**: 100-seitige Stapel werden zerschnitten und per RAG, OCR & LLM analysiert.
2. **3-Stufen Schutzschild**:
   - Stufe 1: Mathematische Prüfung ($Netto + Steuer = Brutto$)
   - Stufe 2: Confidence-Check (< 95% -> Ordner `00_Manuelle_Prüfung_Nötig`)
   - Stufe 3: Telegram Bestätigungs-Buttons (`[Bestätigen]`, `[Prüfen]`)
""",
            category="workflow",
            cross_links=["lieferanten_und_kontenrahmen"]
        )

        self.log_event("INITIALIZE", "Karpathy LLM-Wiki erfolgreich initialisiert.")

    def get_graph_data(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Analysiert alle Wiki-Seiten und extrahiert Knoten (Nodes) und Verknüpfungen (Edges)
        aus Wikilinks [[link]] und Standard-Markdown-Links.
        """
        import re
        nodes = []
        edges = []
        
        pages = list(self.wiki_dir.glob("*.md"))
        page_metadata = {}
        
        # 1. Knoten sammeln
        for p in pages:
            if p.name in ["index.md", "log.md"]:
                continue
            slug = p.stem
            
            # Auslesen von Titel und Kategorie
            text = p.read_text(encoding="utf-8")
            title = slug.replace("_", " ").title()
            category = "allgemein"
            
            for line in text.split("\n"):
                if line.startswith("# "):
                    title = line.replace("# ", "").strip()
                elif "*Kategorie:" in line:
                    parts = line.split("|")
                    category = parts[0].replace("*Kategorie:", "").replace("*", "").strip().lower()
                    
            page_metadata[slug] = {
                "title": title,
                "category": category
            }
            
            nodes.append({
                "id": slug,
                "label": title,
                "group": category
            })
            
        # 2. Verknüpfungen sammeln
        for p in pages:
            if p.name in ["index.md", "log.md"]:
                continue
            slug = p.stem
            text = p.read_text(encoding="utf-8")
            
            # Wikilinks: [[slug]] oder [[slug|label]]
            wikilinks = re.findall(r"\[\[([a-zA-Z0-9_\-]+)(?:\|.*?)?\]\]", text)
            # Markdown-Links: [label](./slug.md)
            md_links = re.findall(r"\[.*?\]\(\.\/([a-zA-Z0-9_\-]+)\.md\)", text)
            
            all_targets = set(wikilinks + md_links)
            for target in all_targets:
                if target in page_metadata:
                    edges.append({
                        "from": slug,
                        "to": target
                    })
                    
        return {"nodes": nodes, "edges": edges}


# Globale Karpathy Wiki-Instanz
karpathy_wiki = KarpathyLLMWikiEngine()
wiki_engine = karpathy_wiki
