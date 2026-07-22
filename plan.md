1. **Create the Tool File (`src/core/reconcile_document_entities.py`):**
   - Import necessary libraries (`sqlite3`, `argparse`, `json`, `csv`, `pathlib`, etc.).
   - Define a function `reconcile_entities(db_path, report_dir, apply, dry_run)` to hold the core logic.
   - Inside the core function:
     - Connect to the `rag_index.db` SQLite database using a context manager.
     - Execute the SQLite Backup API (`sqlite3.connect(backup_db).backup(source_db)`) to create a backup file before applying changes if `apply` is True, into `data/backups/entity_reconciliation/<timestamp>/rag_index.db`. Then run `PRAGMA integrity_check` on the backup DB and abort if it fails.
     - Extract data using JOINs between `belege` and `contact_entities`, potentially using `sevdesk_contacts` and `contact_evidence` or by running separate queries to aggregate all identities.
     - Iterate through `belege`, extracting the known identifiers (from the raw document and existing mapping in the database):
       - Strong IDs: USt-ID, IBAN, Email, SevDesk-ID.
       - Weak IDs: OCR text, filename, supplier name.
     - Check for conflicts:
       - Are there different strong identifiers pointing to different contacts?
       - Does a strong identifier point to Contact A, while OCR/Name/Filename heavily points to Contact B?
       - Does the current `contact_entity_id` contradict a newly discovered strong identity?
       - Can multiple plausible contacts not be definitively excluded?
       - If any of these are true, set status to `REVIEW_CONFLICT`. Do not update `belege.contact_entity_id`.
     - Check for safe matches:
       - At least one strong ID points exactly to one entity.
       - All existing strong IDs confirm the same entity.
       - No other evidence suggests a concrete opposing candidate.
       - If safe, this is a positive match.
     - Update `belege.contact_entity_id` if it's a positive match and `apply` is true. Ensure updates are within a transaction.
   - Aggregate statistics (Before/After numbers).
   - Write reports to `report_dir`:
     - `summary.json`: Statistics of the run.
     - `conflicts.csv`: List of `REVIEW_CONFLICT`s.
     - `audit.jsonl`: Audit log of what was evaluated and changed.

2. **Create the Test File (`tests/test_entity_reconciliation.py`):**
   - Create a synthetic test database fixture (`rag_index.db` schema).
   - Insert the five known Frischeparadies conflict cases:
     - Saved supplier: Frischeparadies.
     - Filename/OCR: Jensmann or Transgourmet.
     - Ensure the test asserts that these result in `REVIEW_CONFLICT` and no changes are made.
   - Include tests for successful idempotent updates based on strong IDs.
   - Include tests for backup functionality and rollback on error.

3. **Complete pre commit steps**
   - Call `pre_commit_instructions` to fetch necessary verification steps.
   - Ensure `tests/test_entity_reconciliation.py` passes using `python3 -m pytest tests/test_entity_reconciliation.py`.
   - Run linter/type checker if requested by pre-commit instructions.

4. **Submit the change.**
   - Commit the changes and submit the branch.
