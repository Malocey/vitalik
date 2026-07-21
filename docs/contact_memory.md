# Dublettenfreies Kontaktgedächtnis

Das Kontaktgedächtnis ergänzt `data/rag_index.db` automatisch aus sicher
verarbeiteten Belegen. Importierte sevDesk-Datensätze bleiben unverändert in
`sevdesk_contacts`; die kanonische, lernende Sicht liegt in `contact_entities`.

## Wachstumsregeln

Ein Kontakt wird nur gelernt, wenn der Beleg `validation_status == PASSED` und
`confidence_score >= 0.90` besitzt. Lieferanten werden aus `lieferant`, Kunden aus
`kunde`, `kundenname` oder `rechnungsempfaenger` übernommen. Ein Beleg kann beide
Rollen liefern.

Die Identität wird in dieser Reihenfolge abgeglichen:

1. USt-ID,
2. IBAN,
3. E-Mail,
4. spätere sevDesk-ID,
5. normalisierter Name zusammen mit PLZ und Ort,
6. bereits bestätigter Alias.

Groß-/Kleinschreibung, Unicode-Varianten, Abstände und übliche Trennzeichen werden
normalisiert. Unterschiedliche Schreibweisen werden als Alias derselben Entität
gespeichert. Ein Geschäftspartner kann die Rolle `customer`, `supplier` oder
`both` besitzen.

## Dublettenschutz

- SQLite-Unique-Indizes schützen starke Identifikatoren.
- `BEGIN IMMEDIATE` serialisiert konkurrierende Zuordnungen.
- Derselbe Beleg zählt durch `contact_evidence` nur einmal als Evidenz.
- Widersprüchliche starke Identifikatoren erzeugen `REVIEW_CONFLICT` und keine
  zweite Entität.
- Unsichere oder unbekannte Namen verändern die Datenbank nicht.
- Die Pipeline lernt erst nach bestätigter RAG-/Wiki-Persistenz.

## Verwendung bei zukünftigen Belegen

`ContactMemory.match_text()` sucht ausschließlich bestätigte, exakte normalisierte
Aliase. Ein gelernter Lieferant kann dadurch bei späteren Dokumenten schon vor dem
LLM als Stammdatenkontext verwendet werden. Fuzzy-Raten erzeugt keine automatische
Zuordnung.

## Tabellen

- `contact_entities`: kanonische Geschäftspartner und optionale sevDesk-Verknüpfung
- `contact_aliases`: belegte Namensvarianten pro Rolle
- `contact_evidence`: eindeutige Beziehung zwischen Kontakt und Beleg

Bank- und Kontaktdaten werden nicht in den Vektorindex oder vollständige
Wiki-Seiten geschrieben. Belegseiten enthalten lediglich die interne
`contact_entity_id`, wenn das Kontaktgedächtnis die Zuordnung geliefert hat.
