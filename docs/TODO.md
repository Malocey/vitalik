# Zukünftige Erweiterungen & To-Do Liste

Diese Liste sammelt geplante Features und strategische Erweiterungen für das Digitale Nervensystem, insbesondere im Hinblick auf den Ausbau der autonomen KI-Agenten über das Model Context Protocol (MCP).

## MCP Server Erweiterungen
- [x] **RAG-Gedächtnis (Wiki & Vektoren):** Tools zum strukturierten Auslesen (`list`, `read`) und Beschreiben (`write`) des Obsidian-Wikis und flüchtigen Vektorgedächtnisses.
- [ ] **Erweiterter sevDesk-Sync (Bidirektional):** Intelligenter Abgleich von Rechnungsnummern, damit lokal und in sevDesk erfasste Belege nicht zu Dubletten führen. Markierung von sevDesk-Downloads als `origin: sevdesk`, um Upload-Loops in der lokalen Pipeline zu vermeiden.
- [ ] **Kalender / Buchungssystem (CalDAV):** Anbindung des Unternehmenskalenders. Die KI kann freie Termine (z.B. für Catering) prüfen, blocken und direkt an sevDesk-Aufträge knüpfen.
- [ ] **Echte Telegram-Integration:** Ersetzen des aktuellen Telegram-Mocks durch einen echten Bot, damit die KI über den MCP-Server Push-Nachrichten an Vitalis Handy senden und Antworten empfangen kann.
- [ ] **E-Mail & Inbox-Management:** Anbindung der `email_decision_engine` an MCP, sodass die KI neue Kundenanfragen lesen, automatisch Angebote in sevDesk entwerfen und Antwort-Mails generieren kann.
- [ ] **sevDesk Deep-Dive:** Tools zur Konvertierung von Angeboten in Rechnungen und zum Prüfen offener Posten (Mahnwesen).

## Architektur & Pipeline
- [ ] **Höchste Priorität: Hybride Streaming-Architektur V2:** Umbau der `PDFEngine` auf ein "Sliding Window" (Scanner liest immer nur z.B. 3 Dokumente im Voraus, um RAM-Abstürze bei 160-Seiten-Scans zu verhindern). Einführung einer lernfähigen Layout-Datenbank, damit deterministische Skripte die Datenextraktion übernehmen und die KI nur noch als Fallback bei unbekannten Layouts einspringt. (Siehe `docs/STREAMING_ARCHITECTURE_V2.md`).
- [ ] Evaluierung des Fast Lane Benchmarks.
- [ ] Verknüpfung des Preis-Monitors (Inflationstracking) mit den Artikelpreisen in sevDesk.
