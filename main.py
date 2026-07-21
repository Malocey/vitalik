"""
Haupteinstiegspunkt (CLI) für das Digitale Nervensystem von VG Delikatessen.
Ermöglicht RAG-Wiki-Abfragen, Schreibstil-Training, Testdaten-Ingestion, lokale OCR und Pipeline-Durchläufe.
"""

import argparse
import sys
from pathlib import Path

# Windows UTF-8 Terminal Support
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.core.config import TESTDATA_DIR, WIKI_DIR
from src.core.rag_engine import rag_engine
from src.wiki.wiki_engine import wiki_engine
from src.core.persona_style import persona_engine
from src.core.local_llm_client import default_llm_client
from pipeline import archive_pipeline


def main():
    parser = argparse.ArgumentParser(description="VG Delikatessen - Digitales Nervensystem CLI")
    parser.add_argument("--init-wiki", action="store_true", help="Initialisiert das RAG-Wiki mit Standardseiten")
    parser.add_argument("--rag-query", type=str, help="Führt eine semantische RAG-Abfrage aus")
    parser.add_argument("--ingest-testdata", action="store_true", help="Indexiert alle Dateien in data/testdata/ im RAG-System")
    parser.add_argument("--add-persona-note", type=str, help="Fügt eine neue persönliche/geschäftliche Kontext-Notiz hinzu")
    parser.add_argument("--test-pipeline", action="store_true", help="Führt einen Test-Durchlauf der Beleg-Pipeline aus")
    
    args = parser.parse_args()

    # 1. Wiki initialisieren
    if args.init_wiki:
        print("[System] Initialisiere RAG-Wiki...")
        wiki_engine.initialize_default_wiki()
        print(f"[System] Wiki erfolgreich unter {WIKI_DIR} erstellt und indexiert.")
        return

    # 2. Testdaten indexieren
    if args.ingest_testdata:
        print(f"[System] Indexiere Testdaten aus {TESTDATA_DIR}...")
        rag_engine.ingest_directory(TESTDATA_DIR)
        print("[System] Testdaten erfolgreich im RAG-Vektorindex gespeichert.")
        return

    # 3. Persona Notiz hinzufügen
    if args.add_persona_note:
        persona_engine.update_profile(new_notes=args.add_persona_note)
        # Auch ins Wiki eintragen
        wiki_engine.create_or_update_page(
            slug="privater_und_geschaeftlicher_kontext",
            title="Privater und Geschäftlicher Kontext",
            content=f"### Ergänzung\n- {args.add_persona_note}",
            category="persona"
        )
        print(f"[System] Persona-Profil & RAG-Wiki aktualisiert mit: '{args.add_persona_note}'")
        return

    # 4. RAG Abfrage
    if args.rag_query:
        query = args.rag_query
        print(f"\n[RAG-Wiki Suche]: '{query}'")
        results = rag_engine.search(query, top_k=3)
        
        print("\n--- Gefundene Wissens-Abschnitte ---")
        for idx, res in enumerate(results, 1):
            print(f"[{idx}] {res['title']} (Score: {res['score']})\n    {res['content'][:200]}...\n")

        system_prompt = persona_engine.build_system_prompt(query)
        rag_context = "\n\n".join([r['content'] for r in results])
        user_prompt = f"Basierend auf folgendem Wissensstand:\n{rag_context}\n\nFrage: {query}"
        
        print("[Generiere Antwort im Schreibstil von Vitalik...]\n")
        response = default_llm_client.generate_completion(user_prompt, system_prompt=system_prompt)
        print(response)
        return

    # 5. Test-Pipeline ausführen
    if args.test_pipeline:
        print("[System] Starte Test-Durchlauf der Beleg-Pipeline (mit lokaler OCR & 3-Stufen Schutzschild)...")
        sample_pdf = TESTDATA_DIR / "sample_scan.pdf"
        if not sample_pdf.exists():
            sample_pdf.write_text("Dummy PDF Content für Test-Scan VG Delikatessen Metzgerei 107.00 EUR", encoding="utf-8")
        
        results = archive_pipeline.process_pdf_archive(sample_pdf)
        print(f"\n[Pipeline-Durchlauf abgeschlossen] {len(results)} Dokument(e) verarbeitet.")
        for r in results:
            doc = r["doc"]
            print(f"\n• Beleg: {doc.get('lieferant')} ({doc.get('brutto')} €)")
            print(f"  Validierung: {doc.get('validation_status')} -> {r['reason']}")
            print(f"  Speicherpfad (MockDrive): {r['saved_path']}")
            print(f"  Telegram Push Preview:\n{r['telegram_msg']}")
        return

    # Standard-Hilfe wenn keine Flags übergeben wurden
    if len(sys.argv) == 1:
        parser.print_help()


if __name__ == "__main__":
    main()
