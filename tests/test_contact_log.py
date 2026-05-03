import json

import pytest
from pydantic import ValidationError

from contact_log import ContactReader, ContactRecord, ContactWriter


def test_contact_record_requires_email_and_session_id():
    """email and session_id are required — no anonymous contact, no orphan record."""
    # Both required fields present → valid
    rec = ContactRecord(
        timestamp="2026-05-03T12:00:00+00:00",
        session_id="abc-123",
        turn_index=3,
        email="recruiter@example.com",
    )
    assert rec.email == "recruiter@example.com"
    assert rec.session_id == "abc-123"
    # Missing email → ValidationError
    with pytest.raises(ValidationError):
        ContactRecord(
            timestamp="2026-05-03T12:00:00+00:00",
            session_id="abc-123",
            turn_index=3,
        )
    # Missing session_id → ValidationError (the join key for linking to interaction log)
    with pytest.raises(ValidationError):
        ContactRecord(
            timestamp="2026-05-03T12:00:00+00:00",
            turn_index=3,
            email="r@example.com",
        )


def test_contact_record_optional_fields_default_none():
    """name and note are optional — submit with only email is valid."""
    rec = ContactRecord(
        timestamp="2026-05-03T12:00:00+00:00",
        session_id="s1",
        turn_index=3,
        email="r@example.com",
    )
    assert rec.name is None
    assert rec.note is None


def test_contact_writer_appends_jsonl_record(tmp_path):
    """ContactWriter.append writes one JSONL line per call; readable as JSON."""
    log = tmp_path / "contacts.jsonl"
    writer = ContactWriter(log)
    writer.append(
        ContactRecord(
            timestamp="2026-05-03T12:00:00+00:00",
            session_id="s1",
            turn_index=3,
            name="Alice",
            email="alice@example.com",
            note="follow up about the AI engineer role",
        )
    )
    lines = log.read_text().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["session_id"] == "s1"
    assert parsed["email"] == "alice@example.com"
    assert parsed["name"] == "Alice"
    assert parsed["note"] == "follow up about the AI engineer role"


def test_contact_writer_creates_parent_directory_if_missing(tmp_path):
    """Writer creates the parent dir on first write — symmetry with LogWriter; no manual mkdir needed."""
    log = tmp_path / "nested" / "contacts.jsonl"
    writer = ContactWriter(log)
    writer.append(
        ContactRecord(
            timestamp="2026-05-03T12:00:00+00:00",
            session_id="s1",
            turn_index=0,
            email="r@example.com",
        )
    )
    assert log.exists()


def test_contact_writer_appends_multiple_records_in_order(tmp_path):
    """Multiple appends produce one line per record, preserving insertion order."""
    log = tmp_path / "contacts.jsonl"
    writer = ContactWriter(log)
    for i in range(3):
        writer.append(
            ContactRecord(
                timestamp=f"2026-05-03T12:00:0{i}+00:00",
                session_id=f"s{i}",
                turn_index=i,
                email=f"r{i}@example.com",
            )
        )
    lines = log.read_text().splitlines()
    assert len(lines) == 3
    assert [json.loads(l)["session_id"] for l in lines] == ["s0", "s1", "s2"]


def test_contact_reader_returns_empty_list_when_file_missing(tmp_path):
    """Missing contacts.jsonl is the no-contacts-yet state — reader returns []."""
    reader = ContactReader(tmp_path / "does_not_exist.jsonl")
    assert reader.read_all() == []


def test_contact_reader_roundtrips_writer_records(tmp_path):
    """Writer → Reader roundtrip — records read back equal records written."""
    log = tmp_path / "contacts.jsonl"
    writer = ContactWriter(log)
    written = ContactRecord(
        timestamp="2026-05-03T12:00:00+00:00",
        session_id="abc",
        turn_index=3,
        name="Bob",
        email="bob@example.com",
        note="hi",
    )
    writer.append(written)
    reader = ContactReader(log)
    records = reader.read_all()
    assert len(records) == 1
    assert records[0]["session_id"] == "abc"
    assert records[0]["email"] == "bob@example.com"


def test_contact_writer_accepts_dict_payload(tmp_path):
    """Writer accepts either ContactRecord or dict — convenience for app.py form-submit handlers."""
    log = tmp_path / "contacts.jsonl"
    writer = ContactWriter(log)
    writer.append({
        "timestamp": "2026-05-03T12:00:00+00:00",
        "session_id": "s1",
        "turn_index": 3,
        "email": "r@example.com",
    })
    parsed = json.loads(log.read_text().strip())
    assert parsed["email"] == "r@example.com"
