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
import os
from pathlib import Path
from typing import Dict, Any, List

# Windows UTF-8 Terminal Support
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel

# Projektpfad auflösen
sys.path.append(str(Path(__file__).resolve().parent))

from src.core.config import BASE_DIR, DATA_DIR, TESTDATA_DIR, WIKI_DIR, MOCK_DRIVE_DIR
from src.core.rag_engine import rag_engine
from src.wiki.wiki_engine import karpathy_wiki, wiki_engine
from src.core.persona_style import persona_engine
from src.core.local_llm_client import default_llm_client
from pipeline import archive_pipeline
from src.parser.document_type_classifier import document_type_classifier
from src.parser.pdf_engine import pdf_engine
from src.parser.analyzer import document_analyzer
from src.core.validation_shield import validation_shield
from src.core.mocks import mock_drive, mock_telegram, mock_sevdesk
from src.core.admin_security import (
    RemoteAdminAuthMiddleware, require_role, resolve_allowed_path,
    safe_contact_entity, safe_job,
)
from src.core.admin_service import (
    audit_event, health_snapshot, processing_control, read_redacted_logs,
)

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

class AdminActionRequest(BaseModel):
    action: str
    job_id: str = ""


app = FastAPI(title="VG Delikatessen Dashboard Server", version="2.0")

app.add_middleware(RemoteAdminAuthMiddleware)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver", "*.ts.net"],
)

DASHBOARD_DIR = BASE_DIR / "dashboard"
DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

# Belege werden absichtlich nicht als unauthentisierte statische Dateien gemountet.

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

@app.get("/admin", response_class=HTMLResponse)
async def read_admin_console():
    admin_file = DASHBOARD_DIR / "admin.html"
    if admin_file.exists():
        return admin_file.read_text(encoding="utf-8")
    raise HTTPException(status_code=404, detail="admin.html nicht gefunden")


# API Endpoints
from src.core.contact_memory import contact_memory

@app.get("/api/stats")
async def get_stats():
    return {
        "vector_documents_count": len(rag_engine.documents),
        "wiki_pages_count": len(list(WIKI_DIR.glob("*.md"))),
        "contact_entities_count": contact_memory.count_entities(),
        "persona_name": persona_engine.profile.get("name"),
        "unternehmen": persona_engine.profile.get("unternehmen"),
        "tonalitaet": persona_engine.profile.get("tonalitaet"),
        "karpathy_pattern": "Karpathy LLM-Wiki Active (index.md + log.md)",
        "fast_lane_router": "Adaptive Fast Lane Active"
    }

@app.get("/api/jobs")
async def get_jobs(request: Request):
    require_role(request, {"viewer", "operator", "admin"})
    try:
        jobs = archive_pipeline.job_adapter.engine.repo.list_jobs(limit=100)
        stats = archive_pipeline.job_adapter.engine.get_progress_summary()
        safe_jobs = [safe_job(job) for job in jobs]
        return {"status": "success", "summary": stats, "jobs": safe_jobs}
    except Exception as e:
        return {"status": "error", "message": str(e), "summary": {}, "jobs": []}

@app.get("/api/contacts")
async def get_contacts(request: Request):
    require_role(request, {"viewer", "operator", "admin"})
    try:
        entities = contact_memory.get_all_entities()
        return {
            "status": "success",
            "total_entities": len(entities),
            "entities": [safe_contact_entity(entity) for entity in entities]
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "entities": []}

@app.get("/api/fast-lane")
async def get_fast_lane_stats():
    try:
        jobs = archive_pipeline.job_adapter.engine.repo.list_jobs(limit=200)
        committed_jobs = [j for j in jobs if j.get("status") == "COMMITTED"]
        return {
            "status": "success",
            "fast_lane_active": True,
            "measurement_status": "benchmark_required",
            "total_committed_jobs": len(committed_jobs),
            "estimated_speedup": None
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

from src.core.matching_engine import matching_engine
from src.core.price_monitor import price_monitor

@app.get("/api/matching")
async def get_matching():
    try:
        matches = matching_engine.get_all_matches()
        return {"status": "success", "total_matches": len(matches), "matches": matches}
    except Exception as e:
        return {"status": "error", "message": str(e), "matches": []}

@app.get("/api/price-trends")
async def get_price_trends():
    try:
        trends = price_monitor.get_price_trends()
        warnings_count = sum(1 for t in trends if t.get("status") == "PREISERHOEHUNG_WARNUNG")
        return {"status": "success", "total_items": len(trends), "warnings_count": warnings_count, "trends": trends}
    except Exception as e:
        return {"status": "error", "message": str(e), "trends": []}

@app.get("/api/admin/health")
async def get_admin_health(request: Request):
    require_role(request, {"viewer", "operator", "admin"})
    return health_snapshot(archive_pipeline, default_llm_client, rag_engine)

@app.get("/api/admin/logs")
async def get_admin_logs(request: Request, limit: int = 200):
    require_role(request, {"operator", "admin"})
    return {"status": "success", "lines": read_redacted_logs(limit)}

@app.post("/api/admin/action")
async def post_admin_action(request: Request, command: AdminActionRequest):
    identity = require_role(request, {"operator", "admin"})
    if request.headers.get("x-vitalik-action") != "confirmed":
        raise HTTPException(status_code=400, detail="Explicit action confirmation header missing")
    action = command.action.strip().lower()
    if action == "pause":
        processing_control.set_paused(True)
    elif action == "resume":
        processing_control.set_paused(False)
    elif action == "release_expired_leases":
        archive_pipeline.job_adapter.engine.release_expired_leases()
    elif action == "retry_job" and command.job_id:
        if not archive_pipeline.job_adapter.engine.retry_job(command.job_id):
            raise HTTPException(status_code=409, detail="Job cannot be retried from its current state")
    else:
        raise HTTPException(status_code=400, detail="Action is not allowlisted")
    audit_event(identity.login, action, command.job_id)
    return {"status": "success", "action": action}

@app.get("/api/wiki")
async def get_wiki():
    pages = []
    for p in sorted(WIKI_DIR.rglob("*.md")):
        if p.name.casefold() in ["index.md", "log.md"] or any("archive" in part.casefold() for part in p.relative_to(WIKI_DIR).parts):
            continue
        rel_path = p.relative_to(WIKI_DIR).with_suffix('').as_posix()
        node_id = f"wiki:{rel_path}"
        pages.append({
            "slug": node_id,
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
    db_path = str(DATA_DIR / "rag_index.db")
    return wiki_engine.get_graph_data(db_path=db_path)

@app.post("/api/rag")
async def post_rag(request: QueryRequest):
    query = request.query
    results = rag_engine.search(query, top_k=3)
    
    system_prompt = persona_engine.build_system_prompt(query)
    rag_context = "\n\n".join([r["content"] for r in results])
    user_prompt = f"Basierend auf folgendem Wissensstand:\n{rag_context}\n\nFrage: {query}"
    
    answer = default_llm_client.generate_completion(user_prompt, system_prompt=system_prompt)
    
    # Automatisch ins Wiki speichern für Gedächtniserweiterung
    try:
        saved_path = karpathy_wiki.save_compounding_answer(query, answer)
        logger.info(f"[RAG-Memory] Antwort automatisch gespeichert: {saved_path}")
    except Exception as e:
        logger.warning(f"[RAG-Memory] Fehler beim Speichern der Antwort: {e}")
    
    karpathy_wiki.log_event("QUERY", f"RAG-Abfrage: '{query[:40]}' → Antwort im Wiki gespeichert")

    return {
        "query": query,
        "answer": answer,
        "retrieved_chunks": results,
        "memory_saved": True,
    }

from src.core.email_decision_engine import email_decision_engine
from src.core.email_draft_generator import email_draft_generator

@app.get("/api/email/drafts")
async def get_email_drafts(request: Request):
    require_role(request, {"viewer", "operator", "admin"})
    try:
        drafts = email_draft_generator.get_pending_drafts()
        return {"status": "success", "total_drafts": len(drafts), "drafts": drafts}
    except Exception as e:
        return {"status": "error", "message": str(e), "drafts": []}

from src.parser.multi_format_engine import multi_format_engine

@app.post("/api/scan-directory")
async def post_scan_directory(request: ScanRequest):
    dir_str = request.directory_path.strip()
    inbox_dir = DATA_DIR / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    configured_roots = [
        Path(value).expanduser().resolve()
        for value in os.getenv("REMOTE_SCAN_ROOTS", "").split(os.pathsep)
        if value.strip()
    ] or [TESTDATA_DIR.resolve(), inbox_dir.resolve()]
    try:
        target_dir = resolve_allowed_path(
            Path(dir_str).expanduser() if dir_str else inbox_dir, configured_roots
        )
    except ValueError:
        raise HTTPException(status_code=403, detail="Verzeichnis liegt außerhalb der freigegebenen Scan-Wurzeln.")

    if not target_dir.exists():
        raise HTTPException(status_code=400, detail=f"Verzeichnis '{target_dir}' existiert nicht auf dem System.")

    scanned_results = []
    supported_extensions = list(multi_format_engine.SUPPORTED_EXTENSIONS)
    files = []
    for candidate in target_dir.rglob("*"):
        if not candidate.is_file() or candidate.suffix.lower() not in supported_extensions:
            continue
        resolved = candidate.resolve()
        if target_dir == resolved or target_dir in resolved.parents:
            files.append(resolved)

    non_pdf_files = [path for path in files if path.suffix.lower() != ".pdf"]
    batch_pages_info = multi_format_engine.extract_batch_parallel(non_pdf_files, max_workers=8)

    for file_path in files:
        try:
            if file_path.suffix.lower() == ".pdf":
                pipeline_results = archive_pipeline.process_pdf_archive(file_path, source_action="keep")
                for result in pipeline_results:
                    doc = result.get("doc", {})
                    scanned_results.append({
                        "filename": file_path.name, "lieferant": doc.get("lieferant"),
                        "brutto": doc.get("brutto"), "netto": doc.get("netto"),
                        "steuer": doc.get("steuer"), "skr03": doc.get("skr03_konto"),
                        "validation_status": doc.get("validation_status"),
                        "reason": result.get("reason"), "saved_path": result.get("saved_path"),
                    })
                continue
            pages_info = batch_pages_info.get(str(file_path)) or multi_format_engine.extract_document(file_path)
            email_text = pages_info[0]["full_text"] if pages_info else ""
            
            dt_res = document_type_classifier.classify(email_text)
            dt_type = dt_res.get("document_type")

            extracted_docs = document_analyzer.analyze_page_stack(pages_info)
            
            for doc in extracted_docs:
                if dt_type and dt_type != "Sonstiges":
                    doc["belegtyp"] = dt_type

                if file_path.suffix.lower() in [".eml", ".msg"]:
                    classification = email_decision_engine.classify_email({
                        "subject": file_path.stem,
                        "from": file_path.name,
                        "body": email_text
                    })
                    if classification.get("supplier_name"):
                        doc["lieferant"] = classification["supplier_name"]

                    if dt_type and dt_type != "Sonstiges":
                        doc["belegtyp"] = dt_type
                    elif classification.get("intent") == "PREIS_ERHOEHUNG":
                        doc["belegtyp"] = "Preiserhöhungs-Mitteilung"
                        doc["skr03_konto"] = "3400"
                    else:
                        doc["belegtyp"] = "E-Mail Korrespondenz"

                    draft = email_draft_generator.generate_draft({
                        "subject": file_path.stem,
                        "from": file_path.name,
                        "body": email_text
                    }, classification)
                    logger.info(f"[E-Mail-Draft] KI-Entwurf '{draft['draft_id']}' für '{file_path.name}' generiert.")

                passed, reason, enriched_doc = validation_shield.validate_document(doc)
                sort_result = multi_format_engine.persist_non_pdf_document(file_path, enriched_doc)
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


def run_dashboard_server(port: int = 8000, host: str = "127.0.0.1"):
    import uvicorn
    print(f"\n=======================================================")
    print(f"🚀 VG Delikatessen Dashboard (FastAPI & Graph) gestartet!")
    print(f"👉 Öffne im Browser: http://localhost:{port}")
    print(f"=======================================================\n")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_dashboard_server(
        port=int(os.getenv("DASHBOARD_PORT", "8000")),
        host=os.getenv("DASHBOARD_HOST", "127.0.0.1"),
    )
