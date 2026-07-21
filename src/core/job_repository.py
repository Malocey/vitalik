import sqlite3
import time
import os
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

DB_PATH_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'document_jobs.db')

class JobRepository:
    def __init__(self, db_path: str = DB_PATH_DEFAULT):
        self.db_path = db_path
        self.local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self.local, 'conn'):
            # Create data dir if not exists
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=30.0) # Busy-timeout
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self.local.conn = conn
        return self.local.conn

    def _init_db(self):
        conn = self._get_connection()
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS document_jobs (
                    job_id TEXT PRIMARY KEY,
                    source_path TEXT,
                    source_md5 TEXT,
                    page_start INTEGER,
                    page_end INTEGER,
                    status TEXT,
                    attempt_count INTEGER DEFAULT 0,
                    locked_by TEXT,
                    lock_expires_at REAL,
                    last_error TEXT,
                    last_failed_stage TEXT,
                    next_retry_at REAL,
                    created_at REAL,
                    updated_at REAL,
                    UNIQUE(source_md5, page_start, page_end)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON document_jobs(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lock ON document_jobs(lock_expires_at);")

    def create_job(self, job_data: Dict[str, Any]) -> str:
        """
        Creates a new job. Idempotent based on unique constraint (source_md5, page_start, page_end).
        Returns the job_id of the created or existing job.
        """
        conn = self._get_connection()
        now = time.time()

        try:
            with conn:
                conn.execute("""
                    INSERT INTO document_jobs (
                        job_id, source_path, source_md5, page_start, page_end,
                        status, attempt_count, locked_by, lock_expires_at,
                        last_error, last_failed_stage, next_retry_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job_data['job_id'], job_data.get('source_path'), job_data['source_md5'],
                    job_data.get('page_start'), job_data.get('page_end'),
                    job_data.get('status', 'DISCOVERED'), 0, None, None,
                    None, None, 0, now, now
                ))
            return job_data['job_id']
        except sqlite3.IntegrityError:
            # Job already exists for this md5 and page range
            cursor = conn.cursor()
            cursor.execute("""
                SELECT job_id FROM document_jobs
                WHERE source_md5 = ? AND page_start IS ? AND page_end IS ?
            """, (job_data['source_md5'], job_data.get('page_start'), job_data.get('page_end')))
            row = cursor.fetchone()
            if row:
                return row['job_id']
            raise # Should not happen unless there's another integrity error

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM document_jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def find_claimable_jobs(self, limit: int = 1) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        now = time.time()
        # Find jobs that are in a ready state and either have no lease, or their lease is expired
        # Also respect next_retry_at
        # RETRY_PENDING is claimable once next_retry_at is reached
        cursor.execute("""
            SELECT * FROM document_jobs
            WHERE status IN ('DISCOVERED', 'OCR_COMPLETE', 'ANALYSIS_COMPLETE', 'RETRY_PENDING')
              AND (locked_by IS NULL OR lock_expires_at < ?)
              AND (next_retry_at IS NULL OR next_retry_at <= ?)
            ORDER BY created_at ASC
            LIMIT ?
        """, (now, now, limit))
        return [dict(row) for row in cursor.fetchall()]

    def claim_job(self, job_id: str, worker_id: str, lease_duration: float) -> bool:
        """Atomically claims a job if it's available or lease has expired."""
        conn = self._get_connection()
        now = time.time()
        expires_at = now + lease_duration

        with conn:
            cursor = conn.execute("""
                UPDATE document_jobs
                SET locked_by = ?, lock_expires_at = ?, updated_at = ?
                WHERE job_id = ?
                  AND status IN ('DISCOVERED', 'OCR_COMPLETE', 'ANALYSIS_COMPLETE', 'RETRY_PENDING')
                  AND (locked_by IS NULL OR lock_expires_at < ?)
            """, (worker_id, expires_at, now, job_id, now))
            return cursor.rowcount > 0

    def renew_lease(self, job_id: str, worker_id: str, lease_duration: float) -> bool:
        """Atomically renews a lease if still owned by the worker."""
        conn = self._get_connection()
        now = time.time()
        expires_at = now + lease_duration

        with conn:
            cursor = conn.execute("""
                UPDATE document_jobs
                SET lock_expires_at = ?, updated_at = ?
                WHERE job_id = ? AND locked_by = ? AND lock_expires_at >= ?
            """, (expires_at, now, job_id, worker_id, now))
            return cursor.rowcount > 0

    def update_job_status(self, job_id: str, worker_id: str, new_status: str,
                          clear_lease: bool = False, error: Optional[str] = None,
                          next_retry_at: Optional[float] = None,
                          increment_attempt: bool = False,
                          last_failed_stage: Optional[str] = None) -> bool:
        """Updates job status. Must be owned by the worker to update."""
        conn = self._get_connection()
        now = time.time()

        updates = ["status = ?", "updated_at = ?"]
        params = [new_status, now]

        if clear_lease:
            updates.append("locked_by = NULL")
            updates.append("lock_expires_at = NULL")

        if error is not None:
            updates.append("last_error = ?")
            params.append(error)

        if next_retry_at is not None:
            updates.append("next_retry_at = ?")
            params.append(next_retry_at)

        if increment_attempt:
            updates.append("attempt_count = attempt_count + 1")

        if last_failed_stage is not None:
            updates.append("last_failed_stage = ?")
            params.append(last_failed_stage)

        query = f"""
            UPDATE document_jobs
            SET {", ".join(updates)}
            WHERE job_id = ? AND locked_by = ? AND lock_expires_at >= ?
        """
        params.extend([job_id, worker_id, now])

        with conn:
            cursor = conn.execute(query, tuple(params))
            return cursor.rowcount > 0

    def get_expired_leases(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        now = time.time()
        cursor.execute("""
            SELECT * FROM document_jobs
            WHERE locked_by IS NOT NULL AND lock_expires_at < ?
        """, (now,))
        return [dict(row) for row in cursor.fetchall()]

    def reset_job_lease(self, job_id: str, new_status: str, last_failed_stage: str, next_retry_at: float, increment_attempt: bool = True):
        """Used when a lease expires to reset the job state. Safely updates only if still expired or locked."""
        conn = self._get_connection()
        now = time.time()

        attempt_update = "attempt_count + 1" if increment_attempt else "attempt_count"

        with conn:
            # Add safe condition to avoid double-processing if another thread already reset it
            conn.execute(f"""
                UPDATE document_jobs
                SET status = ?, last_failed_stage = ?, next_retry_at = ?, attempt_count = {attempt_update},
                    locked_by = NULL, lock_expires_at = NULL, updated_at = ?
                WHERE job_id = ? AND (locked_by IS NOT NULL AND lock_expires_at < ?)
            """, (new_status, last_failed_stage, next_retry_at, now, job_id, now))

    def get_progress_summary(self) -> Dict[str, int]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM document_jobs
            GROUP BY status
        """)
        rows = cursor.fetchall()

        counts = {row['status']: row['count'] for row in rows}

        total = sum(counts.values())
        completed = counts.get('COMMITTED', 0)
        failed = counts.get('FAILED', 0)
        review_required = counts.get('REVIEW_REQUIRED', 0)
        retry_pending = counts.get('RETRY_PENDING', 0)

        running = sum(v for k, v in counts.items() if k.endswith('_RUNNING'))

        remaining = total - completed - failed - review_required

        return {
            "total": total,
            "completed": completed,
            "running": running,
            "retry_pending": retry_pending,
            "review_required": review_required,
            "failed": failed,
            "remaining": remaining
        }

    def clear_database(self):
        """Only for testing."""
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM document_jobs")
