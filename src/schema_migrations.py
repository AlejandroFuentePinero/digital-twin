"""Read-time schema migration for the canonical interaction log (issue #48).

Insulates the reader from every schema bump shipped so far (#37 / #39 / #42)
and from future ones. Runs upstream of `InteractionRecord.model_validate`
in `log_reader._parse_jsonl_to_records`, so both `LocalReader` and
`HFLogReader` share the same upgrade pass.

Three jobs:

1. **Fill missing optional fields with their defaults.** A v1 record on
   disk lacks the reproducibility fields (#37) and the canary fields
   (#39); a v2 record lacks the canary fields. Pydantic would default
   them on validate, but doing the fill explicitly here keeps the
   per-version contract documented in one place — the test suite locks
   it.

2. **Raise on missing required fields with a triage-friendly error.**
   `MissingRequiredFieldError` extends `ValueError` so the reader's
   existing `except (json.JSONDecodeError, ValueError)` skip-with-warning
   path catches it without a new try/except. The error message names
   the missing field plus the record's `session_id` + `turn_index` so
   a malformed line on disk is locatable.

3. **Forward-compat: pass future-version records through unchanged.** A
   producer running schema v5 against a v4 reader must not crash — the
   dashboard keeps rendering the records it can validate and ignores
   the rest. We log one warning at the call site so the skew is visible
   without flooding the log.

On-disk records are never rewritten; this is read-time only. Pair with
`log_reader._smart_normalize_event_type` which similarly upgrades pre-v4
gap-shaped records without touching the file.
"""

from __future__ import annotations

import logging
from typing import Any

from interaction_log import SCHEMA_VERSION

_log = logging.getLogger(__name__)


# Required at every schema version — a record missing one of these is
# malformed regardless of the `schema_version` stamp. The handler raises
# `MissingRequiredFieldError` with the field name + session_id + turn_index
# so a bad line on disk is locatable for triage.
REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "timestamp",
        "session_id",
        "turn_index",
        "question",
        "event_type",
        "branch",
        "classification_confidence",
        "attempts",
        "retrieved_chunks",
        "latency_ms",
        "knew_answer",
    }
)

# Cumulative optional-field defaults per schema version. Each entry is the
# full set of optionals a record at that version is expected to carry.
# The handler fills any missing entries using the target_version's set.
#
# Versions (reconstructed from `git log -p src/interaction_log.py`):
# - v1 (base): the original shape — no reproducibility, no canary, no
#   classifier_labels (added separately in #15 with no schema bump).
# - v2 (#37): adds reproducibility (`git_sha`, `model_id`, `temperature`,
#   `prompt_hash`).
# - v3 (#39): adds canary (`is_canary`, `replicate_index`, `run_id`).
# - v4 (#42): producer-side fix — emits all four `EventType` values via
#   `event_classifier`. Field-identical to v3.

_V1_OPTIONAL_DEFAULTS: dict[str, Any] = {
    "classifier_labels": [],
    "tool_calls": [],
    "contact_offered": False,
    "contact_provided": False,
}
_REPRO_OPTIONAL_DEFAULTS: dict[str, Any] = {
    "git_sha": None,
    "model_id": None,
    "temperature": None,
    "prompt_hash": None,
}
_CANARY_OPTIONAL_DEFAULTS: dict[str, Any] = {
    "is_canary": False,
    "replicate_index": None,
    "run_id": None,
}

OPTIONAL_DEFAULTS_BY_VERSION: dict[str, dict[str, Any]] = {
    "1": dict(_V1_OPTIONAL_DEFAULTS),
    "2": {**_V1_OPTIONAL_DEFAULTS, **_REPRO_OPTIONAL_DEFAULTS},
    "3": {**_V1_OPTIONAL_DEFAULTS, **_REPRO_OPTIONAL_DEFAULTS, **_CANARY_OPTIONAL_DEFAULTS},
    "4": {**_V1_OPTIONAL_DEFAULTS, **_REPRO_OPTIONAL_DEFAULTS, **_CANARY_OPTIONAL_DEFAULTS},
}


class MissingRequiredFieldError(ValueError):
    """Raised when a record on disk is missing a field that's required at
    every schema version. Subclasses `ValueError` so the reader's existing
    skip-with-warning path catches it without a new `except` clause."""


def SchemaVersionHandler(
    record: dict, target_version: str = SCHEMA_VERSION
) -> dict:
    """Upgrade an on-disk record to the reader's target schema version.

    Returns a new dict; the caller's input is never mutated. If the
    record's `schema_version` is higher than `target_version`, logs one
    warning and returns the record unchanged (forward-compat — let
    pydantic decide whether the extra/missing fields validate). On a
    missing required field, raises `MissingRequiredFieldError`. Otherwise
    fills any missing optional field using `OPTIONAL_DEFAULTS_BY_VERSION`
    for `target_version`.
    """
    # A record with no `schema_version` stamp is treated as current —
    # matches pydantic's existing field default and the longstanding
    # `LocalReader` skew tolerance. Records with an explicit stamp keep
    # it (preserved through the migration so triage can spot legacy
    # shapes; the smart-normalize layer also keys off this).
    record_version = str(record.get("schema_version", target_version))

    if _version_gt(record_version, target_version):
        _log.warning(
            "Record schema_version=%s is ahead of reader target=%s; "
            "passing through unchanged (session_id=%s, turn_index=%s).",
            record_version,
            target_version,
            record.get("session_id"),
            record.get("turn_index"),
        )
        return record

    missing_required = [f for f in REQUIRED_FIELDS if f not in record]
    if missing_required:
        sid = record.get("session_id", "<unknown>")
        tix = record.get("turn_index", "<unknown>")
        raise MissingRequiredFieldError(
            f"Record missing required field(s) {sorted(missing_required)} "
            f"(session_id={sid!r}, turn_index={tix!r})."
        )

    defaults = OPTIONAL_DEFAULTS_BY_VERSION.get(
        target_version, OPTIONAL_DEFAULTS_BY_VERSION[SCHEMA_VERSION]
    )
    upgraded = dict(record)
    upgraded.setdefault("schema_version", record_version)
    for field, default in defaults.items():
        if field in upgraded:
            continue
        upgraded[field] = list(default) if isinstance(default, list) else default
    return upgraded


def _version_gt(a: str, b: str) -> bool:
    """Compare schema versions as ints when both parse, else lexically.
    Schema versions are int-shaped today ("1".."4"); the lexical fallback
    keeps the handler well-defined if a future producer ships a non-int
    stamp before the reader catches up."""
    try:
        return int(a) > int(b)
    except (ValueError, TypeError):
        return a > b
