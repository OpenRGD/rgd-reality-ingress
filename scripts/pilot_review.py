"""Trusted-owner pilot review harness, NOT a deployed consumer/API.

Composes the existing A04/A05/A06 interfaces without issuing references,
granting access, reading devices, releasing raw data, or changing the store.
The operator must quiesce legacy writers and keep checkpoint hashes
independently; serialize policy changes with the review on the trusted host.
"""
from dataclasses import dataclass
import json
import re

from reality_ingress.evidence_access import LocalEvidenceReader
from reality_ingress.integrity_inspection import verify_selected
from reality_ingress.temporal_review import TemporalReview, PRESENTATIONS
from reality_ingress.bounded_intake import MAX_LINE_BYTES
from reality_ingress.generic import SCHEMA_REF

@dataclass(frozen=True)
class GateResult:
    status: str
    stage: str
    reason: str
    receipt_age_state: str = "UNKNOWN"
    live_delivery: bool = False
    physical_authorized: bool = False

def review_record(reader, temporal, owner, channel, observation_id, *,
                  expected_checkpoint_sha256, presentation="ARCHIVE_READ"):
    """Owner-only check of a selected original IMU record; summary only.

    The checkpoint must already be approved and independently retained by the
    owner. A04's authorized read returns bytes only inside this trusted process.
    A05 compares the selected snapshot and A06 is invoked only on success.
    No new grant is minted. This is not an atomic cross-component transaction.
    """
    if type(reader) is not LocalEvidenceReader or type(temporal) is not TemporalReview:
        return GateResult("BLOCKED", "CONFIGURATION", "EXISTING_READER_REQUIRED")
    try:
        reader.stats(owner)
        temporal.stats(owner)
    except (ValueError, TypeError):
        return GateResult("BLOCKED", "CONFIGURATION", "OWNER_REQUIRED")
    if (type(expected_checkpoint_sha256) is not str or
        re.fullmatch(r"[0-9a-f]{64}", expected_checkpoint_sha256) is None or
        type(presentation) is not str or presentation not in PRESENTATIONS):
        return GateResult("BLOCKED", "CONFIGURATION", "CHECKPOINT_OR_PRESENTATION_REQUIRED")

    view = reader.read(channel, observation_id, purpose="diagnostics", include_payload=True)
    if (view.status, view.availability) != ("PAYLOAD_RESOLVED", "AVAILABLE"):
        return GateResult("BLOCKED", "A04", view.availability)
    # Pinned development harness, same private store as the existing reader.
    # No caller path or alternate root can redirect the integrity inspection.
    # _root and _root_check are internal seams; review before a public API.
    try:
        reader._root_check()
        proof = verify_selected(reader._root, observation_id,
                                expected_checkpoint_sha256=expected_checkpoint_sha256,
                                max_payload_bytes=MAX_LINE_BYTES)
        reader._root_check()
        if (proof.status != "CHECKED" or
                proof.checkpoint_status != "MATCHED_SUPPLIED_CHECKPOINT"):
            return GateResult("BLOCKED", "A05", proof.reason)
        cp = proof.checkpoint
        ref = json.loads(view.reference_json)
        if (cp.envelope_schema != SCHEMA_REF or
            proof.envelope_integrity != "GENERIC_CONTENT_MATCHED" or
            cp.observation_id != ref["observation_id"] or
            cp.payload_sha256 != ref["payload_sha256_hex"] or
            cp.payload_size_bytes != ref["payload_size_bytes"]):
            return GateResult("BLOCKED", "A05", "VIEW_CHECKPOINT_MISMATCH")
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, AttributeError):
        return GateResult("BLOCKED", "A05", "LOCAL_CHECK_REJECTED")

    # No host-clock claim is supplied by this first pilot: archived receipt
    # freshness remains UNKNOWN. No downstream consumer/History event.
    result = temporal.assess(owner, view, presentation=presentation)
    if result.status == "DUPLICATE":
        return GateResult("DUPLICATE", "A06", result.reason)
    if result.status != "ASSESSED":
        return GateResult("BLOCKED", "A06", result.reason)
    try:
        report = json.loads(result.assessment_json)
        if (report["observation_id"] != observation_id or
            report["live_delivery"] is not False or
            report["decision_eligible"] is not False or
            report["receipt_age_state"] != "UNKNOWN" or
            report["source_measurement_freshness"] != "UNKNOWN" or
            report["chronograf_anchor_ref"] is not None or
            any(report[k] is not False for k in ("source_verified", "robot_binding_verified",
                                                "history_committed", "actuation_enabled"))):
            return GateResult("BLOCKED", "A06", "UNEXPECTED_TEMPORAL_AUTHORITY")
    except (TypeError, ValueError, KeyError):
        return GateResult("BLOCKED", "A06", "INVALID_TEMPORAL_REPORT")
    return GateResult("REVIEWED", "A06", "STORED_EVIDENCE_ONLY")
