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
import yaml
import sqlite3
import hashlib
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
    def __init__(self, wiki_dir: Path = WIKI_DIR, rag=None):
        self.wiki_dir = wiki_dir
        self.rag = rag or rag_engine
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
        # Das chronologische Betriebslog ist Navigation, kein Fachwissen. Würde
        # es bei jedem Ereignis vollständig indiziert, verdrängen Wiederholungen
        # die eigentlichen Lieferanten- und Sachthemen aus den Treffern.

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
        self.rag.index_document(
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
        """Verdichtet einen Beleg in eine kanonische Entitätsseite.

        Der Einzelbeleg bleibt vollständig in SQLite und unter raw_sources. Im
        aktiven Wiki entsteht dagegen genau eine Seite je Lieferant/Kunde.
        """
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

        page_path = self.update_contact_page(doc_data, beleg_id)
        doc_data["wiki_path"] = str(page_path)
        return page_path

    @staticmethod
    def _entity_slug(name: str, entity_id: str = "") -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
        if normalized:
            return normalized[:80]
        digest = hashlib.sha256((entity_id or name).encode("utf-8")).hexdigest()[:12]
        return f"unbekannt-{digest}"

    def update_contact_page(
        self, doc_data: Dict[str, Any], beleg_id: str, synchronize: bool = True
    ) -> Path:
        """Schreibt eine kompakte, idempotente Lieferanten-Hubseite."""
        name = str(doc_data.get("lieferant") or "Unbekannter Lieferant").strip()
        entity_id = str(doc_data.get("contact_entity_id") or "").strip()
        normalized_name = re.sub(r"[^a-z0-9]+", "", name.casefold())
        unresolved = normalized_name in {
            "", "unknown", "unbekannt", "unbekannterlieferant", "bank",
            "dublittemd5", "fehler",
        }
        if unresolved:
            name, entity_id, slug = "Ungeklärte Belege", "review_unresolved", "unresolved-documents"
            page_path = self.wiki_dir / "review" / f"{slug}.md"
            entity_type, category = "review_queue", "prüfung"
        else:
            slug = self._entity_slug(name, entity_id)
            page_path = self.wiki_dir / "entities" / "suppliers" / f"{slug}.md"
            entity_type, category = "supplier", "lieferant"
        page_path.parent.mkdir(parents=True, exist_ok=True)

        sources: Dict[str, Dict[str, str]] = {}
        existing_categories = set()
        existing_accounts = set()
        if page_path.exists():
            existing_text = page_path.read_text(encoding="utf-8")
            for label in re.findall(r"\[\[article_category_[^|\]]+\|([^\]]+)\]\]", existing_text):
                if label.casefold() not in {"rechnung", "beleg", "dokument", "unbekannt"}:
                    existing_categories.add(label)
            account_match = re.search(r"^skr03_accounts:\s*(\[.*\])$", existing_text, re.MULTILINE)
            if account_match:
                try:
                    existing_accounts.update(json.loads(account_match.group(1)))
                except json.JSONDecodeError:
                    pass
            for line in existing_text.splitlines():
                match = re.match(r"- `([^`]+)` \| ([^|]*) \| ([^|]*) \| (.*)", line)
                if match:
                    sources[match.group(1)] = {
                        "datum": match.group(2).strip(), "betrag": match.group(3).strip(),
                        "link": match.group(4).strip(),
                    }
        link = str(doc_data.get("beleg_link") or doc_data.get("raw_text_path") or "").strip()
        rendered_link = f"[Quelle](<{link}>)" if link else "Quelle in SQLite"
        sources[str(beleg_id)] = {
            "datum": str(doc_data.get("datum") or "unbekannt"),
            "betrag": f"{doc_data.get('brutto', '')} EUR",
            "link": rendered_link,
        }
        article_categories = {
            str(item.get("kategorie") or "").strip()
            for item in (doc_data.get("sevdesk_artikel_matches") or [])
            if isinstance(item, dict)
        }
        categories = sorted(existing_categories | article_categories | {
            str(doc_data.get("warengruppe") or "").strip()
        } - {"", "Unbekannt", "UNKNOWN"})
        accounts = sorted(existing_accounts | {
            str(doc_data.get("skr03_konto") or "").strip()
        } - {""})
        aliases = sorted({name, *(doc_data.get("lieferant_aliases") or [])})
        source_lines = "\n".join(
            f"- `{source_id}` | {item['datum']} | {item['betrag']} | {item['link']}"
            for source_id, item in sorted(sources.items())
        )
        category_links = " ".join(
            f"[[article_category_{self._entity_slug(category).replace('-', '_')}|{category}]]"
            for category in categories
        ) or "Noch nicht sicher bestimmt"
        content = (
            "---\n"
            f"entity_id: \"{entity_id or slug}\"\n"
            f"entity_type: {entity_type}\n"
            f"canonical_name: \"{name.replace(chr(34), chr(39))}\"\n"
            f"aliases: {json.dumps(aliases, ensure_ascii=False)}\n"
            f"article_categories: {json.dumps(categories, ensure_ascii=False)}\n"
            f"skr03_accounts: {json.dumps(accounts, ensure_ascii=False)}\n"
            f"source_count: {len(sources)}\n"
            f"updated: {datetime.now().strftime('%Y-%m-%d')}\n"
            "---\n\n"
            f"# {name}\n*Kategorie: {category}*\n\n"
            "## Verdichtetes Wissen\n\n"
            f"- Rollen: {'Manuelle Prüfung' if unresolved else 'Lieferant'}\n- Belegquellen: {len(sources)}\n"
            f"- Typische Artikelarten/Dokumentarten: {category_links}\n"
            f"- Verwendete SKR03-Konten: {', '.join(accounts) or 'noch nicht sicher bestimmt'}\n\n"
            "## Quellenbelege\n\n"
            f"{source_lines}\n"
        )
        page_path.write_text(content, encoding="utf-8")
        if synchronize:
            self.rag.index_document(
                doc_id=f"wiki_{entity_type}_{entity_id or slug}", title=name,
                content=content, source=str(page_path), category=f"wiki_{category}",
            )
            self.rebuild_index_page()
            self.log_event("UPDATE_ENTITY", f"Lieferant '{name}' mit Quelle {beleg_id} aktualisiert.")
        return page_path

    def rebuild_index_page(self):
        """
        Generiert Karpathy's `index.md` neu.
        Katalog aller Seiten mit Links, Einzeilen-Zusammenfassungen und Kategorien.
        """
        pages = [
            p for p in self.wiki_dir.rglob("*.md")
            if p.name.casefold() not in ["index.md", "log.md"] and not any("archive" in part.casefold() for part in p.relative_to(self.wiki_dir).parts)
        ]

        content = "# 📖 VG Delikatessen LLM-Wiki Index\n"
        content += f"*Persistent Compounding Knowledge Base | Stand: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n"
        content += "--- \n\n"
        content += "## 📁 Inhaltskatalog\n\n"

        categories: Dict[str, List[Dict[str, str]]] = {}

        for p in sorted(pages):
            text = p.read_text(encoding="utf-8")
            title = p.stem.replace("_", " ").title()
            summary = "Keine Zusammenfassung"
            cat = None

            fm = {}
            fm_match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
            if fm_match:
                try:
                    fm = yaml.safe_load(fm_match.group(1)) or {}
                except yaml.YAMLError:
                    pass
                text_body = fm_match.group(2)
            else:
                text_body = text

            if fm and isinstance(fm, dict):
                if "category" in fm:
                    cat = str(fm["category"])
                elif "entity_type" in fm:
                    etype = str(fm["entity_type"])
                    cat_map = {"supplier": "lieferant", "customer": "kunde", "article_category": "artikelart", "review_queue": "prüfung"}
                    cat = cat_map.get(etype)

            lines = text_body.split("\n")
            for line in lines:
                if line.startswith("# "):
                    title = line.replace("# ", "").strip()
                elif "*Kategorie:" in line and not cat:
                    parts = line.split("|")
                    cat = parts[0].replace("*Kategorie:", "").replace("*", "").strip()
                elif line.strip() and not line.startswith("#") and not line.startswith("*"):
                    if summary == "Keine Zusammenfassung":
                        summary = line.strip()[:120]

            if not cat:
                cat = "Allgemein"

            if cat not in categories:
                categories[cat] = []
            relative = p.relative_to(self.wiki_dir).as_posix()
            categories[cat].append({"slug": p.stem, "title": title, "summary": summary, "filename": relative})

        for cat_name, cat_pages in categories.items():
            content += f"### {cat_name.title()}\n"
            for item in cat_pages:
                content += f"- **[{item['title']}](./{item['filename']})**: {item['summary']}...\n"
            content += "\n"

        os.makedirs(os.path.dirname(self.index_file), exist_ok=True)
        self.index_file.write_text(content, encoding="utf-8")
        self.rag.index_document(
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

    def lint_wiki(self, output_dir=None, repair=False, db_path=None) -> Dict[str, Any]:
        """
        Karpathy Lint pass:
        Prüft das Wiki auf Waisen-Seiten (ohne Links), unvollständige Begriffe,
        Dubletten, kaputte Links, fehlende Quellen, fehlerhaftes Frontmatter
        und stellt die Konsistenz des Vektorindex sicher.
        """
        pages = [
            p for p in self.wiki_dir.rglob("*.md")
            if p.name.casefold() not in {"index.md", "log.md"}
            and not any("archive" in part.casefold() for part in p.relative_to(self.wiki_dir).parts)
        ]

        all_links = set()
        incoming_links = {p.name: set() for p in pages}

        broken_markdown_links = []
        broken_wikilinks = []
        duplicate_entity_ids = {}
        slug_to_paths = {}
        invalid_frontmatters = []
        legacy_warnings = []
        missing_sources = []
        missing_article_categories = set()
        entity_id_to_path = {}

        db_conn = None
        db_unavailable = False
        if db_path is None:
            db_path = DATA_DIR / "rag_index.db"

        try:
            db_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            db_conn.execute("SELECT 1 FROM belege LIMIT 1")
        except sqlite3.Error:
            db_unavailable = True
            if db_conn:
                db_conn.close()
                db_conn = None

        page_names = {p.name for p in pages}
        page_stems = {p.stem for p in pages}

        for p in pages:
            text = p.read_text(encoding="utf-8")

            # Duplicate Slugs
            if p.stem not in slug_to_paths:
                slug_to_paths[p.stem] = []
            slug_to_paths[p.stem].append(str(p.relative_to(self.wiki_dir)))

            # Parse frontmatter
            fm = None
            fm_match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
            has_fm = False
            if fm_match:
                has_fm = True
                try:
                    fm = yaml.safe_load(fm_match.group(1))
                    if not isinstance(fm, dict):
                        invalid_frontmatters.append(p.name)
                        fm = None
                except yaml.YAMLError:
                    invalid_frontmatters.append(p.name)

            is_legacy = p.stem in ["vitali_persona_und_stil", "lieferanten_und_kontenrahmen", "beleg_pipeline_anleitung"]

            if not has_fm:
                if is_legacy or "Kategorie: persona" in text or "Kategorie: buchhaltung" in text or "Kategorie: workflow" in text or "Kategorie: konzept" in text:
                    legacy_warnings.append(p.name)
                else:
                    invalid_frontmatters.append(p.name)

            if fm:
                # Check required fields
                required_fields = ["entity_id", "entity_type", "canonical_name", "source_count", "updated"]
                if not all(k in fm for k in required_fields):
                    invalid_frontmatters.append(p.name)
                else:
                    entity_id = fm.get("entity_id")
                    if entity_id:
                        if entity_id in entity_id_to_path:
                            if entity_id not in duplicate_entity_ids:
                                duplicate_entity_ids[entity_id] = [entity_id_to_path[entity_id]]
                            duplicate_entity_ids[entity_id].append(str(p.relative_to(self.wiki_dir)))
                        else:
                            entity_id_to_path[entity_id] = str(p.relative_to(self.wiki_dir))

                    if fm.get("entity_type") == "supplier":
                        if "article_categories" not in fm or "skr03_accounts" not in fm:
                            if p.name not in invalid_frontmatters:
                                invalid_frontmatters.append(p.name)
                        if "article_categories" in fm and isinstance(fm["article_categories"], list):
                            for cat in fm["article_categories"]:
                                missing_article_categories.add(cat)

            # Parse links
            # Markdown links: [label](./slug.md) or [label](slug.md)
            md_links = re.findall(r"\[.*?\]\(\.?/?([a-zA-Z0-9_\-]+)\.md\)", text)
            for target_stem in md_links:
                target_name = f"{target_stem}.md"
                if target_name in incoming_links:
                    incoming_links[target_name].add(p.name)
                if target_name not in page_names:
                    broken_markdown_links.append({"from": p.name, "to": target_name})

            # Wikilinks: [[slug]] or [[slug|label]]
            wikilinks = re.findall(r"\[\[([\w\-]+)(?:\|.*?)?\]\]", text)
            for target_stem in wikilinks:
                target_name = f"{target_stem}.md"
                if target_name in incoming_links:
                    incoming_links[target_name].add(p.name)
                if target_name not in page_names:
                    broken_wikilinks.append({"from": p.name, "to": target_name})
                if target_stem.startswith("article_category_"):
                    cat_name = target_stem.replace("article_category_", "")
                    missing_article_categories.add(cat_name)

            # Check sources
            if fm and fm.get("entity_type") in ["supplier", "review_queue"]:
                source_matches = re.findall(r"^- `([^`]+)` \| .* \| .* \| (.*)", text, re.MULTILINE)
                for source_id, link in source_matches:
                    source_id = source_id.strip()
                    if "DUBLITTE_MD5_NO_SAVE" in source_id:
                        missing_sources.append({"page": p.name, "source_id": source_id, "status": "NON_FILE_SOURCE"})
                        continue

                    if db_unavailable:
                        missing_sources.append({"page": p.name, "source_id": source_id, "status": "SOURCE_DATABASE_UNAVAILABLE (NOT_VERIFIABLE)"})
                        continue

                    if db_conn:
                        cur = db_conn.cursor()
                        cur.execute("SELECT beleg_id FROM belege WHERE beleg_id=?", (source_id,))
                        row = cur.fetchone()
                        if not row:
                            missing_sources.append({"page": p.name, "source_id": source_id, "status": "MISSING_SOURCE"})

        duplicate_slugs = {k: v for k, v in slug_to_paths.items() if len(v) > 1}

        orphans = [p.name for p in pages if len(incoming_links[p.name]) == 0 and p.stem not in ["vitali_persona_und_stil", "lieferanten_und_kontenrahmen", "beleg_pipeline_anleitung", "index", "log"]]

        # Article categories repair logic
        existing_categories = [p.stem.replace("article_category_", "") for p in pages if p.stem.startswith("article_category_")]
        missing_categories = sorted(list(missing_article_categories - set(existing_categories)))
        repaired_categories = []

        if repair and missing_categories:
            categories_dir = self.wiki_dir / "entities" / "categories"
            categories_dir.mkdir(parents=True, exist_ok=True)
            for cat in missing_categories:
                norm_slug = self._entity_slug(cat)
                cat_slug = f"article_category_{norm_slug}"
                cat_path = categories_dir / f"{cat_slug}.md"
                if not cat_path.exists():
                    suppliers_with_cat = []
                    for p in pages:
                        text = p.read_text(encoding="utf-8")
                        fm_match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
                        if fm_match:
                            try:
                                fm = yaml.safe_load(fm_match.group(1))
                                if fm and "article_categories" in fm and cat in fm["article_categories"]:
                                    suppliers_with_cat.append(p.stem)
                            except yaml.YAMLError:
                                pass
                    suppliers_with_cat.sort()
                    relations = "\n".join([f"- [[{s}]]" for s in suppliers_with_cat])

                    content = f"""---
entity_id: "{cat_slug}"
entity_type: article_category
canonical_name: "{cat}"
source_count: {len(suppliers_with_cat)}
generated: true
updated: "{datetime.now().strftime('%Y-%m-%d')}"
---

# {cat}
*Kategorie: artikelart*

Dies ist eine deterministisch generierte Artikelart-Seite für '{cat}'.

## Verknüpfte Lieferanten/Kontakte
{relations}
"""
                    cat_path.write_text(content, encoding="utf-8")
                    repaired_categories.append(cat_slug)

        if db_conn:
            db_conn.close()

        report = {
            "total_pages": len(pages),
            "orphan_pages": orphans,
            "broken_markdown_links": broken_markdown_links,
            "broken_wikilinks": broken_wikilinks,
            "duplicate_entity_ids": duplicate_entity_ids,
            "duplicate_slugs": duplicate_slugs,
            "invalid_frontmatters": invalid_frontmatters,
            "legacy_warnings": legacy_warnings,
            "missing_sources": missing_sources,
            "missing_article_categories": missing_categories,
            "repaired_categories": repaired_categories,
            "status": "HEALTHY" if not (orphans or broken_markdown_links or broken_wikilinks or duplicate_entity_ids or duplicate_slugs or invalid_frontmatters or [s for s in missing_sources if s['status'] == 'MISSING_SOURCE']) else "ISSUES_FOUND",
        }

        # Write reports
        if output_dir is None:
            output_dir = DATA_DIR / "reports" / "wiki_lint"
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = output_dir / "wiki_lint_report.json"
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        md_content = f"# Wiki Lint Report ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"
        md_content += f"Status: **{report['status']}**\n"
        md_content += f"Total Pages: {report['total_pages']}\n\n"

        md_content += "## Orphans\n" + "\n".join(f"- {p}" for p in orphans) + "\n\n"
        md_content += "## Broken Markdown Links\n" + "\n".join(f"- {l['from']} -> {l['to']}" for l in broken_markdown_links) + "\n\n"
        md_content += "## Broken Wikilinks\n" + "\n".join(f"- {l['from']} -> {l['to']}" for l in broken_wikilinks) + "\n\n"
        md_content += "## Duplicate Slugs\n" + "\n".join(f"- {slug}: {', '.join(paths)}" for slug, paths in duplicate_slugs.items()) + "\n\n"
        md_content += "## Duplicate Entity IDs\n" + "\n".join(f"- {eid}: {', '.join(paths)}" for eid, paths in duplicate_entity_ids.items()) + "\n\n"
        md_content += "## Invalid Frontmatters\n" + "\n".join(f"- {p}" for p in invalid_frontmatters) + "\n\n"
        md_content += "## Missing Sources\n" + "\n".join(f"- {s['page']} -> {s['source_id']} ({s['status']})" for s in missing_sources) + "\n\n"
        md_content += "## Missing Article Categories\n" + "\n".join(f"- {c}" for c in missing_categories) + "\n\n"
        md_content += "## Repaired Categories\n" + "\n".join(f"- {c}" for c in repaired_categories) + "\n\n"

        md_path = output_dir / "wiki_lint_report.md"
        md_path.write_text(md_content, encoding="utf-8")

        self.log_event("LINT_PASS", f"Wiki-Lint abgeschlossen. {len(pages)} Seiten geprüft. Status: {report['status']}")
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
        
        pages = [
            page for page in self.wiki_dir.rglob("*.md")
            if page.name.casefold() not in {"index.md", "log.md"}
            and not any("archive" in part.casefold() for part in page.relative_to(self.wiki_dir).parts)
        ]
        page_metadata = {}
        
        # 1. Knoten sammeln
        for p in pages:
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
            slug = p.stem
            text = p.read_text(encoding="utf-8")
            
            # Wikilinks: [[slug]] oder [[slug|label]]
            wikilinks = re.findall(r"\[\[([\w\-]+)(?:\|.*?)?\]\]", text)
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
