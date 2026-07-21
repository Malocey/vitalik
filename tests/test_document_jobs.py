import pytest
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor

from src.core.job_repository import JobRepository
from src.core.document_jobs import DocumentJobEngine

@pytest.fixture
def repo():
    # Use memory database for tests
    r = JobRepository(':memory:')
    r.clear_database()
    return r

@pytest.fixture
def engine(repo):
    return DocumentJobEngine(repository=repo, lease_duration_seconds=1.0, max_retries=3)

def test_job_creation_idempotency(engine):
    job1_id = engine.create_job("path1", "md5-1", 1, 1)
    job2_id = engine.create_job("path2", "md5-1", 1, 1)

    assert job1_id == job2_id

    job3_id = engine.create_job("path1", "md5-2", 1, 1)
    assert job1_id != job3_id

def test_claim_job_exclusive(engine):
    engine.create_job("path", "md5-claim", 1, 1)

    worker1 = "worker-1"
    worker2 = "worker-2"

    # Worker 1 claims job
    job_w1 = engine.claim_next_job(worker1)
    assert job_w1 is not None
    assert job_w1['locked_by'] == worker1

    # Worker 2 tries to claim job, should get None as it's locked
    job_w2 = engine.claim_next_job(worker2)
    assert job_w2 is None

def test_lease_expiration_and_recovery(engine):
    engine.create_job("path", "md5-lease", 1, 1)

    worker = "worker-1"
    job = engine.claim_next_job(worker)
    job_id = job['job_id']

    # Transition to OCR_RUNNING
    assert engine.complete_stage(job_id, worker, 'OCR_RUNNING')

    # Wait for lease to expire (duration is 1.0s)
    time.sleep(1.1)

    # Release expired leases
    engine.release_expired_leases()

    # The job was in OCR_RUNNING, so it should recover to RETRY_PENDING
    recovered_job = engine.repo.get_job(job_id)
    assert recovered_job['status'] == 'RETRY_PENDING'
    assert recovered_job['locked_by'] is None
    assert recovered_job['attempt_count'] == 1

    # Should be claimable again (after backoff)
    # The backoff for attempt 1 is 30s, so it won't be claimable immediately
    # Let's mock time or just check next_retry_at is set
    assert recovered_job['next_retry_at'] > time.time()

def test_backoff_calculation(engine):
    # Test min(30 * 2^(retry_count - 1), 1800)
    assert engine._calculate_backoff(0) == 30.0
    assert engine._calculate_backoff(1) == 30.0
    assert engine._calculate_backoff(2) == 60.0
    assert engine._calculate_backoff(3) == 120.0
    assert engine._calculate_backoff(8) == 1800.0 # 30 * 128 = 3840 -> 1800

def test_max_retries(engine):
    engine.create_job("path", "md5-retry", 1, 1)
    worker = "worker"

    job = engine.claim_next_job(worker)
    job_id = job['job_id']

    # Move it to a running state
    engine.complete_stage(job_id, worker, 'OCR_RUNNING')

    # Fail 3 times (max_retries is 3 for this fixture)
    engine.fail_job(job_id, worker, "error 1")
    job = engine.repo.get_job(job_id)
    assert job['status'] == 'RETRY_PENDING' # Fails to RETRY_PENDING
    assert job['attempt_count'] == 1

    # Reset next_retry_at for testing so it can be picked up
    conn = engine.repo._get_connection()
    with conn:
        conn.execute("UPDATE document_jobs SET next_retry_at = 0 WHERE job_id = ?", (job_id,))

    job = engine.claim_next_job(worker)
    # The claim transitions it from RETRY_PENDING to checkpoint (DISCOVERED)
    assert job['status'] == 'DISCOVERED'
    engine.complete_stage(job_id, worker, 'OCR_RUNNING')

    engine.fail_job(job_id, worker, "error 2")
    job = engine.repo.get_job(job_id)
    assert job['attempt_count'] == 2

    with conn:
        conn.execute("UPDATE document_jobs SET next_retry_at = 0 WHERE job_id = ?", (job_id,))

    job = engine.claim_next_job(worker)
    engine.complete_stage(job_id, worker, 'OCR_RUNNING')

    engine.fail_job(job_id, worker, "error 3")
    job = engine.repo.get_job(job_id)
    assert job['status'] == 'FAILED'
    assert job['attempt_count'] == 3

def test_old_worker_cannot_commit(engine):
    engine.create_job("path", "md5-commit", 1, 1)

    worker1 = "worker-1"
    job = engine.claim_next_job(worker1)
    job_id = job['job_id']
    engine.complete_stage(job_id, worker1, 'OCR_RUNNING')

    # Wait for lease to expire
    time.sleep(1.1)

    # Release leases
    engine.release_expired_leases()

    # Reset next_retry_at via repo directly so it can be claimed immediately
    # Since release_expired_leases sets status to DISCOVERED (as checkpoint), we just update next_retry_at
    conn = engine.repo._get_connection()
    with conn:
        conn.execute("UPDATE document_jobs SET next_retry_at = 0 WHERE job_id = ?", (job_id,))

    worker2 = "worker-2"
    job2 = engine.claim_next_job(worker2)
    assert job2['locked_by'] == worker2

    # Worker 1 tries to commit
    assert not engine.complete_stage(job_id, worker1, 'OCR_RUNNING')

    # Worker 2 can commit
    assert engine.complete_stage(job_id, worker2, 'OCR_RUNNING')

def test_progress_summary(engine):
    engine.repo.create_job({'job_id': '1', 'source_md5': '1', 'status': 'COMMITTED'})
    engine.repo.create_job({'job_id': '2', 'source_md5': '2', 'status': 'COMMITTED'})
    engine.repo.create_job({'job_id': '3', 'source_md5': '3', 'status': 'OCR_RUNNING'})
    engine.repo.create_job({'job_id': '4', 'source_md5': '4', 'status': 'FAILED'})
    engine.repo.create_job({'job_id': '5', 'source_md5': '5', 'status': 'REVIEW_REQUIRED'})
    engine.repo.create_job({'job_id': '6', 'source_md5': '6', 'status': 'DISCOVERED'})

    summary = engine.get_progress_summary()
    assert summary['total'] == 6
    assert summary['completed'] == 2
    assert summary['running'] == 1
    assert summary['failed'] == 1
    assert summary['review_required'] == 1
    assert summary['remaining'] == 2 # DISCOVERED + OCR_RUNNING

def test_parallel_access():
    # Because of threading, we need to make sure the memory db isn't local to a single thread
    # Let's use a file-based temporary db for this test.
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(delete=False) as f:
        db_path = f.name
    try:
        repo = JobRepository(db_path)
        repo.clear_database()
        engine = DocumentJobEngine(repository=repo)

        engine.create_job("path", "md5-parallel", 1, 1)

        # Use multiple threads to claim the same job
        def worker_task(worker_id):
            return engine.claim_next_job(worker_id)

        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(worker_task, [f"worker-{i}" for i in range(5)]))

        # Only one worker should have claimed the job
        claimed = [r for r in results if r is not None]
        assert len(claimed) == 1
        assert claimed[0]['locked_by'] is not None
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
