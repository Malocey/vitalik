from pathlib import Path
import pytest
from src.core.admin_security import (
    mask_identifier, resolve_allowed_path, safe_contact_entity, safe_job,
)
from src.core.admin_service import ProcessingControl


def test_mask_identifier_keeps_only_suffix():
    assert mask_identifier("DE123456789", 4) == "*******6789"
    assert mask_identifier("") == ""


def test_processing_pause_persists(tmp_path):
    state = tmp_path / "state.json"
    control = ProcessingControl(state)
    control.set_paused(True)
    assert ProcessingControl(state).is_paused() is True
    control.set_paused(False)
    assert ProcessingControl(state).is_paused() is False


def test_contact_projection_redacts_sensitive_values():
    entity = safe_contact_entity({
        "entity_id": "E1", "canonical_name": "Test GmbH", "role": "supplier",
        "alias_count": 1, "evidence_count": 2, "tax_id": "DE123456789",
        "iban": "DE00123456789012345678", "email": "secret@example.test",
    })
    assert "123456789" not in entity["tax_id"]
    assert "secret@example.test" not in entity["email"]


def test_path_guard_rejects_outside_root(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    assert resolve_allowed_path(inbox, [inbox]) == inbox.resolve()
    with pytest.raises(ValueError):
        resolve_allowed_path(Path("/"), [inbox])


def test_job_projection_drops_paths_and_checkpoint():
    safe = safe_job({"job_id": "J1", "source_path": "/secret/a.pdf", "source_md5": "abcdef123456",
                     "checkpoint_json": "secret", "locked_by": "worker", "status": "OCR_RUNNING"})
    assert "source_path" not in safe
    assert "checkpoint_json" not in safe
    assert safe["source_hash"].endswith("ef123456")
