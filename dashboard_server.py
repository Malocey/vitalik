#!/usr/bin/env python3
"""
Web Dashboard Server für das Digitale Nervensystem von VG Delikatessen.
Basiert auf FastAPI. Stellt ein interaktives REST-API und Web-Views für:
- Dashboard (Scanner & RAG)
- RAG Playground
- Interaktiver Wiki Graph (Obsidian-Style)
 bereit.
"""

import sys
import logging
from pathlib import Path
from typing import Dict, Any, List

# Windows UTF-8 Terminal Support
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Projektpfad auflösen
sys.path.append(str(Path(__file__).resolve().parent))

from src.core.config import BASE_DIR, DATA_DIR, TESTDATA_DIR, WIKI_DIR, MOCK_DRIVE_DIR
from src.core.rag_engine import rag_engine
from src.wiki.wiki_engine import karpathy_wiki, wiki_engine
from src.core.persona_style import persona_engine
from src.core.local_llm_client import default_llm_client
from pipeline import archive_pipeline
from src.parser.pdf_engine import pdf_engine
from src.parser.analyzer import document_analyzer
from src.core.validation_shield import validation_shield
from src.core.mocks import mock_drive, mock_telegram, mock_sevdesk

logger = logging.getLogger("DashboardServer")

# Models for POST endpoints
class QueryRequest(BaseModel):
    query: str

class ScanRequest(BaseModel):
    directory_path: str = ""

class SaveQueryRequest(BaseModel):
    query: str
    answer: str

class IngestRequest(BaseModel):
    note: str
    title: str = "Geschäftlicher & Privater Kontext"


app = FastAPI(title="VG Delikatessen Dashboard Server", version="2.0")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DASHBOARD_DIR = BASE_DIR / "dashboard"
DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

# Mount Mock Drive folder for direct PDF opening/downloading
if MOCK_DRIVE_DIR.exists():
    app.mount("/static/drive", StaticFiles(directory=str(MOCK_DRIVE_DIR)), name="drive")
    print(f"[DashboardServer] Mock Drive gemountet unter /static/drive ({MOCK_DRIVE_DIR})")

# HTML Page Endpoints
@app.get("/", response_class=HTMLResponse)
async def read_dashboard():
    index_file = DASHBOARD_DIR / "index.html"
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    raise HTTPException(status_code=404, detail="index.html nicht gefunden")

@app.get("/rag", response_class=HTMLResponse)
async def read_rag_playground():
    rag_file = DASHBOARD_DIR / "rag_playground.html"
    if rag_file.exists():
        return rag_file.read_text(encoding="utf-8")
    raise HTTPException(status_code=404, detail="rag_playground.html nicht gefunden")

@app.get("/wiki-graph", response_class=HTMLResponse)
async def read_wiki_graph():
    graph_file = DASHBOARD_DIR / "wiki_graph.html"
    if graph_file.exists():
        return graph_file.read_text(encoding="utf-8")
    raise HTTPException(status_code=404, detail="wiki_graph.html nicht gefunden")

# For fast SPA tab switching - return HTML content only (body stripped)
@app.get("/api/tab-content/rag", response_class=HTMLResponse)
async def get_rag_tab_content():
    rag_file = DASHBOARD_DIR / "rag_playground.html"
    if rag_file.exists():
        content = rag_file.read_text(encoding="utf-8")
        # Extract body content (everything between <body> and </body>)
        start = content.find("<body>") + 6
        end = content.find("</body>")
        if start > 5 and end > start:
            return content[start:end]
        return content
    raise HTTPException(status_code=404, detail="rag_playground.html nicht gefunden")

@app.get("/api/tab-content/wiki", response_class=HTMLResponse)
async def get_wiki_tab_content():
    wiki_file = DASHBOARD_DIR / "wiki_graph.html"
    if wiki_file.exists():
        content = wiki_file.read_text(encoding="utf-8")
        # Extract body content
        start = content.find("<body>") + 6
        end = content.find("</body>")
        if start > 5 and end > start:
            return content[start:end]
        return content
    raise HTTPException(status_code=404, detail="wiki_graph.html nicht gefunden")


# API Endpoints
@app.get("/api/stats")
async def get_stats():
    return {
        "vector_documents_count": len(rag_engine.documents),
        "wiki_pages_count": len(list(WIKI_DIR.glob("*.md"))),
        "persona_name": persona_engine.profile.get("name"),
        "unternehmen": persona_engine.profile.get("unternehmen"),
        "tonalitaet": persona_engine.profile.get("tonalitaet"),
        "karpathy_pattern": "Karpathy LLM-Wiki Active (index.md + log.md)"
    }

@app.get("/api/wiki")
async def get_wiki():
    pages = []
    for p in sorted(WIKI_DIR.glob("*.md")):
        if p.name in ["index.md", "log.md"]:
            continue
        pages.append({
            "slug": p.stem,
            "title": p.stem.replace("_", " ").title(),
            "content": p.read_text(encoding="utf-8")
        })
    return {"pages": pages}

@app.get("/api/wiki/index")
async def get_wiki_index():
    index_path = WIKI_DIR / "index.md"
    content = index_path.read_text(encoding="utf-8") if index_path.exists() else "# No index"
    return {"content": content}

@app.get("/api/wiki/log")
async def get_wiki_log():
    log_path = WIKI_DIR / "log.md"
    content = log_path.read_text(encoding="utf-8") if log_path.exists() else "# No log"
    return {"content": content}

@app.get("/api/wiki-graph")
async def get_wiki_graph_data():
    return wiki_engine.get_graph_data()

@app.post("/api/rag")
async def post_rag(request: QueryRequest):
    query = request.query
    results = rag_engine.search(query, top_k=3)
    
    system_prompt = persona_engine.build_system_prompt(query)
    rag_context = "\n\n".join([r["content"] for r in results])
    user_prompt = f"Basierend auf folgendem Wissensstand:\n{rag_context}\n\nFrage: {query}"
    
    answer = default_llm_client.generate_completion(user_prompt, system_prompt=system_prompt)
    karpathy_wiki.log_event("QUERY", f"RAG-Abfrage: '{query[:40]}'")

    return {
        "query": query,
        "answer": answer,
        "retrieved_chunks": results
    }

@app.post("/api/scan-directory")
async def post_scan_directory(request: ScanRequest):
    dir_str = request.directory_path.strip()
    target_dir = Path(dir_str) if dir_str else TESTDATA_DIR

    if not target_dir.exists():
        raise HTTPException(status_code=400, detail=f"Verzeichnis '{target_dir}' existiert nicht auf dem System.")

    scanned_results = []
    supported_extensions = [".pdf", ".png", ".jpg", ".jpeg", ".txt"]
    files = [f for f in target_dir.rglob("*") if f.is_file() and f.suffix.lower() in supported_extensions]

    if not files:
        return {"status": "warning", "message": f"Keine passenden Belege in {target_dir} gefunden.", "results": []}

    for file_path in files:
        try:
            pages_info = pdf_engine.inspect_pdf(file_path) if file_path.suffix.lower() == ".pdf" else [{
                "page_num": 1,
                "text_snippet": file_path.read_text(encoding="utf-8", errors="ignore")[:500],
                "full_text": file_path.read_text(encoding="utf-8", errors="ignore")
            }]

            extracted_docs = document_analyzer.analyze_page_stack(pages_info)
            
            for doc in extracted_docs:
                passed, reason, enriched_doc = validation_shield.validate_document(doc)
                
                # Zerschneiden und Einsortieren des Belegs über sorter
                sort_result = archive_pipeline.sorter.sort_and_save_pdf(
                    input_pdf_path=file_path,
                    start_page=doc.get("start_seite", 1),
                    end_page=doc.get("end_seite", 1),
                    doc_data=enriched_doc
                )
                saved_path = sort_result["saved_path"]
                
                if passed:
                    mock_sevdesk.post_voucher(enriched_doc)
                tg_msg = mock_telegram.send_approval_request(enriched_doc)

                scanned_results.append({
                    "filename": file_path.name,
                    "lieferant": enriched_doc.get("lieferant"),
                    "brutto": enriched_doc.get("brutto"),
                    "netto": enriched_doc.get("netto"),
                    "steuer": enriched_doc.get("steuer"),
                    "skr03": enriched_doc.get("skr03_konto"),
                    "validation_status": enriched_doc.get("validation_status"),
                    "reason": reason,
                    "saved_path": saved_path,
                    "telegram_msg": tg_msg
                })
        except Exception as e:
            logger.warning(f"Fehler beim Scannen von {file_path.name}: {e}")

    # RAG Ingestion für das gescannte Verzeichnis ausführen
    rag_engine.ingest_directory(target_dir)
    karpathy_wiki.log_event("DIRECTORY_SCAN", f"Ordner '{target_dir.name}' gescannt. {len(scanned_results)} Beleg(e) verarbeitet.")

    return {
        "status": "success",
        "scanned_directory": str(target_dir),
        "total_files": len(files),
        "results": scanned_results
    }

@app.post("/api/wiki/save-query")
async def post_save_query(request: SaveQueryRequest):
    query = request.query
    answer = request.answer
    saved_path = karpathy_wiki.save_compounding_answer(query, answer)
    return {"status": "success", "message": f"Erkenntnis dauerhaft unter {saved_path.name} im Wiki gespeichert."}

@app.post("/api/wiki/lint")
async def post_lint_wiki():
    report = karpathy_wiki.lint_wiki()
    return {"status": "success", "report": report}

@app.post("/api/ingest")
async def post_ingest(request: IngestRequest):
    note = request.note
    title = request.title
    if note:
        persona_engine.update_profile(new_notes=note)
        karpathy_wiki.create_or_update_page(
            slug="privater_und_geschaeftlicher_kontext",
            title=title,
            content=f"### Ergänzung\n- {note}",
            category="persona"
        )
    return {"status": "success", "message": "Informationen erfolgreich im Karpathy-Wiki indexiert."}


def run_dashboard_server(port: int = 8000):
    import uvicorn
    print(f"\n=======================================================")
    print(f"🚀 VG Delikatessen Dashboard (FastAPI & Graph) gestartet!")
    print(f"👉 Öffne im Browser: http://localhost:{port}")
    print(f"=======================================================\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    run_dashboard_server()
