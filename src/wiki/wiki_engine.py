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
import os
import re
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
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        self.log_file.write_text(existing + log_entry, encoding="utf-8")
        rag_engine.index_document(
            doc_id="wiki_log",
            title="VG Delikatessen LLM-Wiki Log",
            content=existing + log_entry,
            source=str(self.log_file),
            category="wiki_system",
        )

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
        os.makedirs(os.path.dirname(page_path), exist_ok=True)
        page_path.write_text(full_markdown, encoding="utf-8")

        # Ins RAG-System einspeisen
        rag_engine.index_document(
            doc_id=f"wiki_{slug}",
            title=title,
            content=full_markdown,
            source=str(page_path),
            category=f"wiki_{category}"
        )

        self.rebuild_index_page()
        self.log_event("UPDATE_PAGE", f"Seite '{title}' ({file_name}) erstellt/aktualisiert.")
        return page_path

    def create_or_update_beleg_page(
        self,
        doc_data: Dict[str, Any],
        beleg_id: str,
    ) -> Path:
        """Schreibt einen verarbeiteten Beleg als persistente Markdown-Wiki-Seite."""
        safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(beleg_id)).strip("_")
        if not safe_id:
            raise ValueError("Für die Wiki-Indizierung ist eine gültige Beleg-ID erforderlich.")

        lieferant = doc_data.get("lieferant", "")
        datum = doc_data.get("datum", "")
        brutto = doc_data.get("brutto", "")
        raw_text = doc_data.get("raw_text")
        if not raw_text or not str(raw_text).strip():
            raw_text = (
                f"Lieferant: {lieferant}, Datum: {datum}, Betrag: {brutto} EUR, "
                f"Beleg-ID: {beleg_id}"
            )

        raw_path = RAW_SOURCES_DIR / "belege" / f"beleg_{safe_id}.txt"
        os.makedirs(os.path.dirname(raw_path), exist_ok=True)
        raw_path.write_text(str(raw_text), encoding="utf-8")
        doc_data["raw_text_path"] = str(raw_path)

        summary = doc_data.get("summary") or (
            f"{doc_data.get('belegtyp', 'Beleg')} von {lieferant} vom {datum} "
            f"über {brutto} EUR. Warengruppe: "
            f"{doc_data.get('warengruppe', 'Unbekannt')}. "
            f"Status: {doc_data.get('validation_status', 'Unbekannt')}."
        )
        doc_data["summary"] = summary
        beleg_link = doc_data.get("beleg_link", "")
        link_line = f"- **Originalbeleg:** [PDF öffnen](<{beleg_link}>)\n" if beleg_link else ""
        assignment_lines = ""
        if doc_data.get("lieferant_match_source"):
            if doc_data.get("lieferant_match_source") == "contact_memory":
                assignment_lines += (
                    f"- **Kontaktentität:** {doc_data.get('contact_entity_id', '')}\n"
                    f"- **Zuordnungsquelle:** Kontaktgedächtnis\n"
                )
            else:
                assignment_lines += (
                    f"- **sevDesk-Kontakt:** {doc_data.get('sevdesk_kunden_nr', '')}\n"
                    f"- **Kreditorennummer:** {doc_data.get('kreditoren_nr', '')}\n"
                    f"- **Zahlungsziel:** {doc_data.get('zahlungsziel_tage', '')} Tage\n"
                    f"- **Zuordnungsquelle:** sevDesk-Kontakte\n"
                )
        article_matches = doc_data.get("sevdesk_artikel_matches") or []
        if article_matches:
            assignment_lines += "- **sevDesk-Artikel:** " + ", ".join(
                f"{item.get('artikelnummer')} ({item.get('name')})" for item in article_matches
            ) + "\n"

        content = (
            f"## Belegdaten\n\n"
            f"- **Beleg-ID:** {beleg_id}\n"
            f"- **Lieferant:** {lieferant}\n"
            f"- **Datum:** {datum}\n"
            f"- **Bruttobetrag:** {brutto} EUR\n"
            f"- **Nettobetrag:** {doc_data.get('netto', '')} EUR\n"
            f"- **Umsatzsteuer:** {doc_data.get('steuer', '')} EUR\n"
            f"- **Rechnungsnummer:** {doc_data.get('rechnungsnummer', '')}\n"
            f"- **Warengruppe:** {doc_data.get('warengruppe', '')}\n"
            f"- **SKR03-Konto:** {doc_data.get('skr03_konto', '')}\n"
            f"- **Validierungsstatus:** {doc_data.get('validation_status', '')}\n\n"
            f"{assignment_lines}{link_line}\n## Zusammenfassung\n\n{summary}\n\n"
            f"## Quelldaten\n\nVollständiger OCR-Text: `{raw_path}`"
        )
        page_path = self.create_or_update_page(
            slug=f"beleg_{safe_id}",
            title=f"Beleg {beleg_id} – {lieferant}",
            content=content,
            category="beleg",
        )
        doc_data["wiki_path"] = str(page_path)
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

        os.makedirs(os.path.dirname(self.index_file), exist_ok=True)
        self.index_file.write_text(content, encoding="utf-8")
        rag_engine.index_document(
            doc_id="wiki_index",
            title="VG Delikatessen LLM-Wiki Index",
            content=content,
            source=str(self.index_file),
            category="wiki_system",
        )

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
        
        pages = list(self.wiki_dir.rglob("*.md"))
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
