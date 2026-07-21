"""Verbindet die bestehende Belegpipeline mit sicheren Job-Checkpoints."""

from typing import Any, Dict, Optional

from src.core.document_jobs import DocumentJobEngine


class PipelineJobAdapter:
    def __init__(self, engine: Optional[DocumentJobEngine] = None):
        self.engine = engine or DocumentJobEngine()

    def acquire(
        self,
        source_path: str,
        document_hash: str,
        page_start: int,
        page_end: int,
        worker_id: str,
    ) -> Optional[Dict[str, Any]]:
        job_id = self.engine.create_job(source_path, document_hash, page_start, page_end)
        job = self.engine.claim_job(job_id, worker_id)
        if job:
            job["job_id"] = job_id
            job["lease_acquired"] = True
            return job
        existing = self.engine.repo.get_job(job_id)
        if existing:
            existing["lease_acquired"] = False
        return existing

    def prepare_analysis(self, job: Dict[str, Any], worker_id: str) -> Optional[Dict[str, Any]]:
        """Erreicht ANALYSIS_RUNNING oder liefert einen sicheren Analysecheckpoint."""
        job_id = job["job_id"]
        status = job["status"]
        if status == "DISCOVERED":
            if not self.engine.complete_stage(job_id, worker_id, "OCR_RUNNING"):
                raise RuntimeError("Job-Lease vor OCR-Start verloren")
            if not self.engine.complete_stage(job_id, worker_id, "OCR_COMPLETE"):
                raise RuntimeError("Job-Lease vor OCR-Checkpoint verloren")
            status = "OCR_COMPLETE"
        if status == "OCR_COMPLETE":
            if not self.engine.complete_stage(job_id, worker_id, "ANALYSIS_RUNNING"):
                raise RuntimeError("Job-Lease vor Analyse verloren")
            return None
        if status == "ANALYSIS_COMPLETE":
            checkpoint = self.engine.load_checkpoint(job_id)
            if checkpoint is None:
                raise RuntimeError("ANALYSIS_COMPLETE ohne gespeicherten Checkpoint")
            return checkpoint
        raise RuntimeError(f"Job kann aus Status {status} nicht analysiert werden")

    def finish_analysis(
        self, job_id: str, worker_id: str, document: Dict[str, Any]
    ) -> None:
        if not self.engine.save_checkpoint(job_id, worker_id, document):
            raise RuntimeError("Job-Lease beim Speichern des Analysecheckpoints verloren")
        if not self.engine.complete_stage(job_id, worker_id, "ANALYSIS_COMPLETE"):
            raise RuntimeError("Job-Lease beim Analyse-Commit verloren")

    def begin_persistence(self, job_id: str, worker_id: str) -> None:
        if not self.engine.complete_stage(job_id, worker_id, "RAG_RUNNING"):
            raise RuntimeError("Job-Lease vor RAG-/Wiki-Persistenz verloren")

    def commit(self, job_id: str, worker_id: str) -> None:
        if not self.engine.complete_stage(job_id, worker_id, "COMMITTED"):
            raise RuntimeError("Job-Lease beim finalen Commit verloren")

    def fail(self, job_id: str, worker_id: str, error: Exception) -> None:
        self.engine.fail_job(job_id, worker_id, str(error))


pipeline_job_adapter = PipelineJobAdapter()
