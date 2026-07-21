from src.core.document_jobs import DocumentJobEngine
from src.core.job_repository import JobRepository
from src.core.pipeline_job_adapter import PipelineJobAdapter


def make_adapter(tmp_path):
    repository = JobRepository(str(tmp_path / "jobs.db"))
    return PipelineJobAdapter(DocumentJobEngine(repository=repository))


def test_checkpoint_survives_new_engine_instance(tmp_path):
    adapter = make_adapter(tmp_path)
    job = adapter.acquire("scan.pdf", "hash-1", 1, 2, "worker-1")
    assert adapter.prepare_analysis(job, "worker-1") is None
    adapter.finish_analysis(job["job_id"], "worker-1", {"lieferant": "Test GmbH"})

    second = PipelineJobAdapter(DocumentJobEngine(
        repository=JobRepository(str(tmp_path / "jobs.db"))
    ))
    # Simulierter Neustart: Lease wird für diesen Test gezielt freigegeben.
    connection = second.engine.repo._get_connection()
    with connection:
        connection.execute(
            "UPDATE document_jobs SET locked_by = NULL, lock_expires_at = NULL WHERE job_id = ?",
            (job["job_id"],),
        )
    resumed = second.acquire("scan.pdf", "hash-1", 1, 2, "worker-2")
    assert second.prepare_analysis(resumed, "worker-2") == {"lieferant": "Test GmbH"}


def test_committed_job_is_not_reacquired(tmp_path):
    adapter = make_adapter(tmp_path)
    job = adapter.acquire("scan.pdf", "hash-2", 1, 1, "worker-1")
    adapter.prepare_analysis(job, "worker-1")
    adapter.finish_analysis(job["job_id"], "worker-1", {"ok": True})
    adapter.begin_persistence(job["job_id"], "worker-1")
    adapter.commit(job["job_id"], "worker-1")

    existing = adapter.acquire("scan.pdf", "hash-2", 1, 1, "worker-2")
    assert existing["status"] == "COMMITTED"
    assert existing["lease_acquired"] is False


def test_checkpoint_write_requires_active_owner(tmp_path):
    adapter = make_adapter(tmp_path)
    job = adapter.acquire("scan.pdf", "hash-3", 1, 1, "owner")
    adapter.prepare_analysis(job, "owner")
    assert not adapter.engine.save_checkpoint(job["job_id"], "other", {"bad": True})
