import sqlite3
from concurrent.futures import ThreadPoolExecutor

from src.core.contact_memory import ContactMemory


def candidate(name="Muster Handel GmbH", **values):
    return {"name": name, "postal_code": "10115", "city": "Berlin", **values}


def test_same_normalized_contact_is_not_duplicated(tmp_path):
    memory = ContactMemory(tmp_path / "contacts.db")
    first = memory.upsert_contact(candidate(), "supplier", "DOC-1", 0.98)
    second = memory.upsert_contact(
        candidate(name="  MUSTER   HANDEL GmbH "), "supplier", "DOC-2", 0.97
    )
    assert first["entity_id"] == second["entity_id"]
    assert second["status"] == "MATCHED"
    assert memory.count_entities() == 1

    with sqlite3.connect(memory.db_path) as db:
        assert db.execute("SELECT evidence_count FROM contact_entities").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM contact_evidence").fetchone()[0] == 2


def test_strong_identifier_matches_name_variant(tmp_path):
    memory = ContactMemory(tmp_path / "contacts.db")
    first = memory.upsert_contact(
        candidate(tax_id="DE 123 456 789"), "customer", "DOC-1", 0.99
    )
    second = memory.upsert_contact(
        candidate(name="Musterhandel", tax_id="DE123456789"), "customer", "DOC-2", 0.99
    )
    assert first["entity_id"] == second["entity_id"]
    assert memory.count_entities() == 1


def test_conflicting_strong_identifier_requires_review(tmp_path):
    memory = ContactMemory(tmp_path / "contacts.db")
    created = memory.upsert_contact(
        candidate(email="office@example.test"), "supplier", "DOC-1", 0.99
    )
    conflict = memory.upsert_contact(
        candidate(email="other@example.test"), "supplier", "DOC-2", 0.99
    )
    assert created["status"] == "CREATED"
    assert conflict["status"] == "REVIEW_CONFLICT"
    assert memory.count_entities() == 1


def test_unsafe_document_does_not_grow_database(tmp_path):
    memory = ContactMemory(tmp_path / "contacts.db")
    result = memory.learn_from_document(
        {"lieferant": "Unsicher GmbH", "validation_status": "PASSED", "confidence_score": 0.7},
        "DOC-1",
    )
    assert result["status"] == "SKIPPED_UNSAFE"
    assert memory.count_entities() == 0


def test_supplier_and_customer_can_be_learned_from_document(tmp_path):
    memory = ContactMemory(tmp_path / "contacts.db")
    result = memory.learn_from_document({
        "lieferant": "Liefer GmbH", "lieferant_plz": "20095", "lieferant_ort": "Hamburg",
        "kunde": "Kunde GmbH", "kunde_plz": "10115", "kunde_ort": "Berlin",
        "validation_status": "PASSED", "confidence_score": 0.98,
    }, "DOC-1")
    assert result["status"] == "LEARNED"
    assert {item["role"] for item in result["entities"]} == {"supplier", "customer"}
    assert memory.count_entities() == 2


def test_parallel_upsert_creates_one_entity(tmp_path):
    db_path = tmp_path / "contacts.db"
    memory = ContactMemory(db_path)

    def write(index):
        return ContactMemory(db_path).upsert_contact(
            candidate(tax_id="DE999999999"), "supplier", f"DOC-{index}", 0.99
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(write, range(6)))
    assert memory.count_entities() == 1
    assert all(result["status"] in {"CREATED", "MATCHED"} for result in results)


def test_same_document_does_not_inflate_evidence(tmp_path):
    memory = ContactMemory(tmp_path / "contacts.db")
    memory.upsert_contact(candidate(), "supplier", "DOC-1", 0.98)
    memory.upsert_contact(candidate(), "supplier", "DOC-1", 0.98)
    with sqlite3.connect(memory.db_path) as db:
        assert db.execute("SELECT evidence_count FROM contact_entities").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM contact_evidence").fetchone()[0] == 1


def test_same_entity_can_be_customer_and_supplier(tmp_path):
    memory = ContactMemory(tmp_path / "contacts.db")
    supplier = memory.upsert_contact(
        candidate(tax_id="DE123456789"), "supplier", "DOC-1", 0.99
    )
    customer = memory.upsert_contact(
        candidate(name="Musterhandel", tax_id="DE123456789"), "customer", "DOC-2", 0.99
    )
    assert supplier["entity_id"] == customer["entity_id"]
    assert memory.count_entities() == 1
    with sqlite3.connect(memory.db_path) as db:
        assert db.execute("SELECT role FROM contact_entities").fetchone()[0] == "both"


def test_learned_alias_is_available_for_future_documents(tmp_path):
    memory = ContactMemory(tmp_path / "contacts.db")
    created = memory.upsert_contact(
        candidate(name="Feinkost Nord GmbH"), "supplier", "DOC-1", 0.98
    )
    match = memory.match_text("Rechnung der FEINKOST NORD GMBH über 119,00 EUR")
    assert match["entity_id"] == created["entity_id"]
    assert match["source"] == "contact_memory"
