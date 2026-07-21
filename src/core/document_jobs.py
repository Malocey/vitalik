import time
import uuid
import logging
from typing import Dict, Any, List, Optional
from src.core.job_repository import JobRepository

logger = logging.getLogger(__name__)

class DocumentJobEngine:
    VALID_NORMAL_TRANSITIONS = {
        'DISCOVERED': ['OCR_RUNNING'],
        'OCR_RUNNING': ['OCR_COMPLETE'],
        'OCR_COMPLETE': ['ANALYSIS_RUNNING'],
        'ANALYSIS_RUNNING': ['ANALYSIS_COMPLETE'],
        'ANALYSIS_COMPLETE': ['RAG_RUNNING'],
        'RAG_RUNNING': ['COMMITTED'],
    }

    # Used for recovery logic
    CHECKPOINT_RECOVERY = {
        'OCR_RUNNING': 'DISCOVERED',
        'ANALYSIS_RUNNING': 'OCR_COMPLETE',
        'RAG_RUNNING': 'ANALYSIS_COMPLETE',
    }

    FINAL_STATES = {'COMMITTED', 'FAILED', 'REVIEW_REQUIRED'}

    def __init__(self, repository: JobRepository = None, lease_duration_seconds: float = 600.0, max_retries: int = 5):
        self.repo = repository or JobRepository()
        self.lease_duration = lease_duration_seconds
        self.max_retries = max_retries

    def _calculate_backoff(self, attempt_count: int) -> float:
        """Exponentieller Backoff: min(30 * 2^(retry_count - 1), 1800) Sekunden"""
        if attempt_count <= 0:
            return 30.0
        return min(30.0 * (2 ** (attempt_count - 1)), 1800.0)

    def create_job(self, source_path: str, source_md5: str, page_start: int = 1, page_end: int = 1) -> str:
        """Creates a new job idempotently. Returns the job ID."""
        job_id = str(uuid.uuid4())
        job_data = {
            'job_id': job_id,
            'source_path': source_path,
            'source_md5': source_md5,
            'page_start': page_start,
            'page_end': page_end,
            'status': 'DISCOVERED'
        }
        return self.repo.create_job(job_data)

    def claim_next_job(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """Finds and claims the next available job."""
        jobs = self.repo.find_claimable_jobs(limit=10)

        for job in jobs:
            if self.repo.claim_job(job['job_id'], worker_id, self.lease_duration):
                claimed_job = self.repo.get_job(job['job_id'])
                if claimed_job and claimed_job['status'] == 'RETRY_PENDING':
                    # Automatically transition from RETRY_PENDING to the last safe checkpoint
                    # Since we've claimed it, we can safely update it.
                    last_failed = claimed_job.get('last_failed_stage')
                    resume_status = self.CHECKPOINT_RECOVERY.get(last_failed, 'DISCOVERED') if last_failed else 'DISCOVERED'
                    # We just update the status, keep the lease
                    self.repo.update_job_status(claimed_job['job_id'], worker_id, resume_status)
                    claimed_job['status'] = resume_status
                return claimed_job

        return None

    def renew_lease(self, job_id: str, worker_id: str) -> bool:
        """Renews the lease for a job."""
        return self.repo.renew_lease(job_id, worker_id, self.lease_duration)

    def complete_stage(self, job_id: str, worker_id: str, new_status: str) -> bool:
        """Progresses the job to the next stage."""
        job = self.repo.get_job(job_id)
        if not job:
            return False

        current_status = job['status']

        # Determine if it's a valid normal transition
        valid_targets = self.VALID_NORMAL_TRANSITIONS.get(current_status, [])
        is_valid_normal = new_status in valid_targets

        # From RETRY_PENDING we can jump back to a RUNNING state
        is_retry_start = current_status == 'RETRY_PENDING' and new_status.endswith('_RUNNING')

        # From DISCOVERED to OCR_RUNNING is normal, handled above.
        # But moving to REVIEW_REQUIRED is also a valid jump from non-final states
        is_review = new_status == 'REVIEW_REQUIRED' and current_status not in self.FINAL_STATES

        if not (is_valid_normal or is_retry_start or is_review):
            logger.warning(f"Invalid transition from {current_status} to {new_status} for job {job_id}")
            return False

        clear_lease = new_status in self.FINAL_STATES

        return self.repo.update_job_status(
            job_id, worker_id, new_status, clear_lease=clear_lease
        )

    def fail_job(self, job_id: str, worker_id: str, error: str) -> bool:
        """Marks a job as failed for the current stage, manages retries."""
        # For fail_job to work after update_job_status with clear_lease=True,
        # we need to be careful if we are clearing the lease.
        # But wait, fail_job clears the lease! So the next fail_job call will find locked_by is None!
        # Ah, fail_job is called from RUNNING state, and it sets it to RETRY_PENDING and clears lease.
        # If the job is then picked up again, it's claimed by a worker again,
        # moving it to RUNNING state. So fail_job shouldn't be called consecutively without claiming.
        # But in the test, we call fail_job again without claiming!
        job = self.repo.get_job(job_id)
        if not job:
            return False

        # In the test, we call fail_job directly on RETRY_PENDING.
        # If locked_by is not the worker, but we're trying to fail it, that's an issue if the worker doesn't own it.
        # But maybe the test should claim it first? Yes, the test should claim the job.

        if job['locked_by'] != worker_id:
            return False

        current_status = job['status']
        attempt_count = job['attempt_count'] + 1

        if attempt_count >= self.max_retries:
            # Reached max retries, mark as FAILED
            return self.repo.update_job_status(
                job_id, worker_id, 'FAILED',
                clear_lease=True, error=error,
                increment_attempt=True, last_failed_stage=current_status
            )
        else:
            # Set to RETRY_PENDING
            backoff = self._calculate_backoff(attempt_count)
            next_retry_at = time.time() + backoff

            return self.repo.update_job_status(
                job_id, worker_id, 'RETRY_PENDING',
                clear_lease=True, error=error,
                next_retry_at=next_retry_at,
                increment_attempt=True, last_failed_stage=current_status
            )

    def release_expired_leases(self):
        """Finds expired leases and resets them based on their checkpoint."""
        expired_jobs = self.repo.get_expired_leases()

        for job in expired_jobs:
            current_status = job['status']

            # We don't want to increment if it's already in RETRY_PENDING,
            # as fail_job already incremented it.
            # But wait, if lease is expired in a RUNNING state, it's a crash.
            # If it's a crash, we increment and set to RETRY_PENDING.

            if current_status == 'RETRY_PENDING':
                # Just clear the lease, attempt_count is already handled
                # Wait, reset_job_lease increments attempt_count. We don't want that if we just clear lease.
                # Actually, release_expired_leases should set it to RETRY_PENDING if it was in RUNNING.
                # If it's already RETRY_PENDING, we just clear the lease.
                self.repo.reset_job_lease(job['job_id'], 'RETRY_PENDING', job.get('last_failed_stage'), job.get('next_retry_at', time.time()), increment_attempt=False)
                continue

            attempt_count = job['attempt_count'] + 1

            if attempt_count >= self.max_retries:
                # Mark as failed directly if max retries reached on lease expiration
                self.repo.reset_job_lease(
                    job['job_id'], 'FAILED', current_status, time.time(), increment_attempt=True
                )
                continue

            backoff = self._calculate_backoff(attempt_count)
            next_retry_at = time.time() + backoff

            # Transition to RETRY_PENDING
            self.repo.reset_job_lease(
                job['job_id'], 'RETRY_PENDING', current_status, next_retry_at, increment_attempt=True
            )

    def retry_job(self, job_id: str) -> bool:
        """Manually trigger retry for a REVIEW_REQUIRED or FAILED job."""
        job = self.repo.get_job(job_id)
        if not job:
            return False

        if job['status'] not in {'REVIEW_REQUIRED', 'FAILED'}:
            return False

        # Determine last safe status based on last_failed_stage if available
        last_failed = job.get('last_failed_stage')
        resume_status = self.CHECKPOINT_RECOVERY.get(last_failed, 'DISCOVERED') if last_failed else 'DISCOVERED'

        # Reset attempts and next_retry_at
        # To do this safely, we claim it temporarily or update directly.
        # Let's bypass worker claim for manual retry, just update it in repo
        conn = self.repo._get_connection()
        with conn:
            cursor = conn.execute("""
                UPDATE document_jobs
                SET status = ?, attempt_count = 0, last_error = NULL,
                    next_retry_at = NULL, locked_by = NULL, lock_expires_at = NULL
                WHERE job_id = ?
            """, (resume_status, job_id))
            return cursor.rowcount > 0

    def get_progress_summary(self) -> Dict[str, int]:
        return self.repo.get_progress_summary()
