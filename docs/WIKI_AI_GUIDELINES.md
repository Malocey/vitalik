# KI-Richtlinien für das Obsidian-Wiki (Best Practices)

Dieses Dokument ist die "Bibel" für alle autonomen KI-Agenten (über den MCP-Server), die das Wiki von VG Delikatessen verwalten. Das Ziel ist ein perfektes, RAG-optimiertes und menschenlesbares Langzeitgedächtnis im Obsidian-Format.

## 1. Das goldene Prinzip: Vektor vs. Wiki
- **Flüchtige Notizen (`memorize_thought`):** Für schnelle Zusammenfassungen, einzelne Ideen oder kurze Erinnerungen ("Kunde X mag keinen Koriander"). Diese werden als Vektoren im RAG gespeichert.
- **Strukturiertes Wissen (`write_wiki_page`):** Für dauerhafte Prozesse, Geschäftskontakte, Rezepte, Catering-Checklisten oder offizielle Unternehmensrichtlinien. Diese müssen als Markdown-Dateien im Wiki abgelegt werden.

## 2. Struktur und Namensgebung (Slugs)
- **Ordner:** Seiten werden typischerweise in thematischen Kategorien/Ordnern abgelegt (z.B. `Rezepte/`, `Kunden/`, `Prozesse/`).
- **Slugs:** Der Bezeichner (Slug) der Seite muss eindeutig, kleingeschrieben und ohne Sonderzeichen/Leerzeichen sein (z.B. `rezepte/rinderbraten_klassik`).

## 3. Zwingendes YAML-Frontmatter
Jede Wiki-Seite MUSS mit einem validen YAML-Frontmatter beginnen. Dies ist für die Metadaten-Extraktion des RAG-Systems entscheidend.
Das Format ist exakt:
```yaml
---
title: "Der Titel der Seite"
date: "YYYY-MM-DD"
category: "Kategorie (z.B. rezept, kunde, prozess)"
tags: ["tag1", "tag2"]
aliases: ["Alternativer Suchbegriff"]
---
```
*(Wichtig: Die drei Bindestriche `---` müssen exakt so stehen, keine Markdown-Codeblöcke darum!)*

## 4. Vernetzung durch Obsidian-Links
Ein gutes RAG-System lebt von einem Graphen. Erwähnst du auf einer Seite eine andere Entität (z.B. einen Lieferanten oder ein anderes Rezept), MUSS diese in doppelten eckigen Klammern verlinkt werden.
- **Falsch:** "Wir kaufen das Fleisch bei Frischeparadies."
- **Richtig:** "Wir kaufen das Fleisch bei [[Lieferanten/Frischeparadies]]."

## 5. Sicherheitsrichtlinien (Markdown Parsing)
- **Kein HTML:** Generiere ausschließlich reines Markdown. Verwende keine HTML-Tags wie `<div>`, `<span>` oder `<script>`. Das Frontend rendert Markdown aus Sicherheitsgründen streng über sichere Parser (Vermeidung von XSS-Schwachstellen, keine Nutzung von `innerHTML`).
- **Tabellen:** Nutze Standard-Markdown-Tabellen für strukturierte Daten (wie Zutatenlisten oder Preislisten).

## 6. Der perfekte Schreibstil
- **Tonalität:** Professionell, klar strukturiert, aber im Geiste der Metzgerei VG Delikatessen (handwerklich, qualitätsbewusst).
- **Formatierung:** Nutze H2 (`##`) und H3 (`###`) Überschriften, Aufzählungszeichen (`-`) und fette Hervorhebungen (`**wichtig**`), um den Text leicht scannbar zu machen.
