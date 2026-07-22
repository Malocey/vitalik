"""Sichere Betriebsfunktionen, Health-Status und redigierte Auditlogs."""

import json
import logging
import os
import re
import shutil
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List

from src.core.config import DATA_DIR


LOG_DIR = DATA_DIR / "logs"
AUDIT_FILE = LOG_DIR / "admin_audit.jsonl"
APP_LOG_FILE = LOG_DIR / "application.log"
STATE_FILE = DATA_DIR / "admin_state.json"
STARTED_AT = time.time()


def configure_application_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if not any(getattr(handler, "baseFilename", None) == str(APP_LOG_FILE) for handler in root.handlers):
        handler = RotatingFileHandler(APP_LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(handler)


def _redact(text: str) -> str:
    text = re.sub(r"(?i)(authorization|token|password|secret)(\s*[:=]\s*)\S+", r"\1\2[REDACTED]", text)
    text = re.sub(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", "[IBAN-REDACTED]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL-REDACTED]", text)
    return text[:4000]


def audit_event(identity: str, action: str, target: str = "", outcome: str = "ok") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "identity": _redact(identity), "action": action,
        "target": _redact(target), "outcome": outcome,
    }
    with AUDIT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


class ProcessingControl:
    def __init__(self, state_file: Path = STATE_FILE):
        self.state_file = state_file
        self._lock = threading.Lock()
        self._paused = self._load()

    def _load(self) -> bool:
        try:
            return bool(json.loads(self.state_file.read_text(encoding="utf-8")).get("paused"))
        except (OSError, ValueError, TypeError):
            return False

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps({"paused": self._paused}), encoding="utf-8")
        temporary.replace(self.state_file)

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused
            self._save()

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def ensure_running(self) -> None:
        if self.is_paused():
            raise RuntimeError("Dokumentverarbeitung wurde im Control Center pausiert")


processing_control = ProcessingControl()
configure_application_logging()


def health_snapshot(archive_pipeline, llm_client, rag_engine) -> Dict[str, Any]:
    disk = shutil.disk_usage(DATA_DIR)
    summary = archive_pipeline.job_adapter.engine.get_progress_summary()
    try:
        workers = llm_client.get_pool_status(check_health=False)
    except Exception as exc:
        workers = [{"status": "error", "message": _redact(str(exc))}]
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - STARTED_AT, 1),
        "processing_paused": processing_control.is_paused(),
        "jobs": summary,
        "workers": workers,
        "storage": {
            "free_gb": round(disk.free / (1024 ** 3), 2),
            "used_gb": round(disk.used / (1024 ** 3), 2),
            "rag_db_mb": round(Path(rag_engine.db_path).stat().st_size / (1024 ** 2), 2)
            if Path(rag_engine.db_path).exists() else 0.0,
        },
    }


def read_redacted_logs(limit: int = 200) -> List[str]:
    limit = max(1, min(int(limit), 1000))
    if not APP_LOG_FILE.exists():
        return []
    with APP_LOG_FILE.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()[-limit:]
    return [_redact(line.rstrip()) for line in lines]
