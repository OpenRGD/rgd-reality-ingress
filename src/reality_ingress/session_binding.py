"""RI-A02: bounded offline source/session correlation for already supplied bytes.

No storage lookup, transport, ACL, attestation, time qualification or actuation.
The caller must obtain each input through an independently authorized reader.
This is a local candidate API, NOT a new wire contract or a new ObservationRef.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from .consumer_ref import unverified_ref_from_envelope
from .generic import (
    SCHEMA_REF as GENERIC_SCHEMA, MEDIA_TYPE, MAX_SAMPLE_BYTES,
    canonical_json, envelope_from_sample, validate_sample,
)

MAX_REF_BYTES = 16 * 1024
MAX_ENVELOPE_BYTES = MAX_SAMPLE_BYTES
MAX_CANDIDATES = 64
MAX_BATCH_BYTES = 4 * 1024 * 1024
CAMERA_SCHEMA = "urn:openrgd:experimental:reality-ingress:observation-envelope:v0"
COG_COPY_PROFILE = "cog-ri-02.console-copy.v0.1-candidate"


class BindingError(ValueError):
    """A stable local diagnostic code, not a payload or path."""


def _require(value, code):
    if not value:
        raise BindingError(code)


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _nonfinite(_):
    raise BindingError("NONFINITE_JSON")


def _decode(raw: bytes, budget: int) -> dict:
    _require(type(raw) is bytes and 0 < len(raw) <= budget, "INPUT_LIMIT")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_nonfinite)
    except BindingError:
        raise
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise BindingError("INVALID_JSON") from None
    _require(type(value) is dict, "INVALID_JSON_OBJECT")
    stack = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        _require(depth <= 32 and nodes <= 100000, "JSON_COMPLEXITY_LIMIT")
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
    # Reject overflowed floats (e.g. 1e999) and invalid Unicode scalars.
    try:
        canonical_json(value)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise BindingError("INVALID_JSON_VALUE") from None
    return value


def _token(value: Any) -> bool:
    return (type(value) is str
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", value) is not None
            and value.lower() not in {"unknown", "none", "null", "unbound", "unavailable"}
            and bool(value.replace("-", "").strip("0")))


@dataclass(frozen=True)
class SessionKey:
    """Exact stored labels; NEVER a verified hardware, host or Life identity."""
    source_id: str
    modality: str
    reference_frame_id: str
    session_id: str
    sequence: int
    clock_domain_id: str
    boot_id: str

    def __post_init__(self):
        for value in (self.source_id, self.modality, self.reference_frame_id,
                      self.session_id, self.clock_domain_id, self.boot_id):
            _require(_token(value), "INVALID_SESSION_KEY")
        _require(type(self.sequence) is int and self.sequence >= 0,
                 "INVALID_SESSION_SEQUENCE")


@dataclass(frozen=True)
class SuppliedEvidence:
    """Immutable, externally authorized inputs; not a grant or store handle."""
    reference: bytes
    envelope: bytes
    payload: bytes

    def __post_init__(self):
        _require(all(type(x) is bytes for x in
                     (self.reference, self.envelope, self.payload)), "INVALID_INPUT_TYPE")


@dataclass(frozen=True)
class SessionBinding:
    observation_id: str
    payload_sha256_hex: str
    key: SessionKey
    received_monotonic_ns: int
    producer_label: str
    # Label equality and content verification, NOT verified origin or access.
    source_verified: bool = False
    robot_binding_verified: bool = False
    publisher_host_id: None = None
    clock_relation: str = "NOT_ESTABLISHED"
    freshness: str = "UNKNOWN"
    history_committed: bool = False
    actuation_enabled: bool = False


@dataclass(frozen=True)
class Resolution:
    status: str
    reason: str
    binding: SessionBinding | None = None
    # Even if source bytes agree, this function never checks a real store's
    # availability, issuer, ACL, physical identity or canonical time.
    reference_issuance_verified: bool = False
    access_verified: bool = False
    store_availability_verified: bool = False


def _compare(evidence: SuppliedEvidence, expected: SessionKey | None) -> Resolution:
    ref = _decode(evidence.reference, MAX_REF_BYTES)
    env = _decode(evidence.envelope, MAX_ENVELOPE_BYTES)
    _require(ref.get("integrity_status") in {"not_verified", "verified_local_hash"},
             "REFERENCE_STATUS_INVALID")
    projected = unverified_ref_from_envelope(env)
    # The existing legacy projection is authoritative for shape only.
    # Never trust or upgrade the supplied verification flag.
    projected["integrity_status"] = ref["integrity_status"]
    _require(canonical_json(projected) == canonical_json(ref), "REFERENCE_ENVELOPE_MISMATCH")
    # Legacy camera IDs are UUIDs; payload equality cannot establish the
    # metadata/session commitment. Do not read or trust image payload here.
    if env["schema_ref_str"] == CAMERA_SCHEMA:
        return Resolution("UNRESOLVED", "LEGACY_CAMERA_SESSION_NOT_BOUND")
    _require(env["schema_ref_str"] == GENERIC_SCHEMA, "UNSUPPORTED_ENVELOPE")
    _require(ref["payload_media_type"] == MEDIA_TYPE, "UNSUPPORTED_MEDIA_TYPE")
    _require(0 < len(evidence.payload) <= MAX_SAMPLE_BYTES, "PAYLOAD_LIMIT")
    digest = hashlib.sha256(evidence.payload).hexdigest()
    _require(ref["payload_size_bytes"] == len(evidence.payload)
             and ref["payload_sha256_hex"] == digest, "PAYLOAD_HASH_OR_SIZE_MISMATCH")
    row = _decode(evidence.payload, MAX_SAMPLE_BYTES)
    validate_sample(row)
    _require(canonical_json(row) == evidence.payload, "NONCANONICAL_GENERIC_PAYLOAD")
    # Reconstruct the exact legacy envelope (including original ID) using its
    # existing implementation. Never accept an input path or dereference it.
    payload_ref = "payloads/" + digest[:2] + "/" + digest + ".bin"
    rebuilt = envelope_from_sample(row, digest, payload_ref, len(evidence.payload))
    _require(canonical_json(rebuilt) == canonical_json(env),
             "GENERIC_ENVELOPE_COMMITMENT_MISMATCH")
    source, stamp, wrapper = row["source"], row["temporal_binding"], row["payload"]
    # A normalized Console-copy proposal is not the approved IMU producer
    # representation. It has its own clock semantics and often no source
    # session field. Never infer session from this nested presentation.
    if wrapper.get("representation_profile") == COG_COPY_PROFILE:
        return Resolution("UNRESOLVED", "CONSOLE_COPY_PROFILE_REVIEW_PENDING")
    session = source.get("session_id_str")
    if session is None:
        return Resolution("UNRESOLVED", "SOURCE_SESSION_NOT_RECORDED")
    _require(_token(session), "INVALID_SOURCE_SESSION")
    domain = stamp["clock_domain_ref"]
    boot, clock = domain.get("boot_id_str"), domain.get("clock_domain_id_str")
    if not _token(boot) or not _token(clock):
        return Resolution("UNRESOLVED", "CLOCK_LABEL_NOT_RESOLVED")
    key = SessionKey(source["source_id_str"], source["modality_str"],
                     source["reference_frame_id_str"], session,
                     source["sample_sequence_uint"], clock, boot)
    if "console_ingest_sample" in wrapper:
        # Reconcile the two copies of source identifiers in the source-owned
        # IMU export. Full numeric correlation remains Console's existing
        # helper; C1 digest and admission remain Cognition's responsibility.
        original = wrapper["console_ingest_sample"]
        _require(type(original) is dict
                 and original.get("schema_version") == "openrgd.imu-sample.v0.1-candidate"
                 and key.modality == "imu", "UNSUPPORTED_IMU_PROFILE")
        _require(original.get("source_id") == key.source_id
                 and original.get("sensor_frame_id") == key.reference_frame_id
                 and original.get("session_id") == key.session_id
                 and type(original.get("sequence")) is int
                 and original["sequence"] == key.sequence
                 and type(original.get("host_monotonic_ns")) is int
                 and original["host_monotonic_ns"] == stamp["received_monotonic_ns"],
                 "ORIGINAL_SOURCE_SAMPLE_MISMATCH")
        _require(all(wrapper.get(flag) is False for flag in (
            "source_verified", "robot_binding_verified", "history_committed",
            "actuation_enabled", "heading_calibrated", "decision_eligible"))
            and wrapper.get("observation_only") is True
            and "calibration_revision" in wrapper and wrapper["calibration_revision"] is None,
            "UNSUPPORTED_IMU_AUTHORITY")
    if expected is not None and key != expected:
        return Resolution("MISMATCH", "SESSION_KEY_MISMATCH")
    producer = row["producer_str"]
    _require(type(producer) is str and 0 < len(producer) <= 256,
             "INVALID_PRODUCER_LABEL")
    binding = SessionBinding(ref["observation_id"], digest, key,
                             stamp["received_monotonic_ns"], producer)
    return Resolution("CONTENT_MATCHED", "SUPPLIED_GENERIC_CONTENT_MATCH", binding)


def resolve_session(evidence: SuppliedEvidence | None, *,
                    expected: SessionKey | None = None) -> Resolution:
    """Inspect one already supplied triple, not the whole archive.

    A match proves correspondence of supplied generic content and labels only.
    Missing bytes are not an assessment of retention or ACL. A match does not
    claim unique identity among unsupplied observations, or grant media access.
    """
    if evidence is None:
        return Resolution("UNRESOLVED", "INPUT_NOT_SUPPLIED")
    if type(evidence) is not SuppliedEvidence or (
            expected is not None and type(expected) is not SessionKey):
        return Resolution("REJECTED", "INVALID_INPUT_TYPE")
    try:
        return _compare(evidence, expected)
    except BindingError as exc:
        return Resolution("REJECTED", str(exc))
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError):
        return Resolution("REJECTED", "INVALID_OR_INCONSISTENT_CONTENT")


def resolve_unique(evidence_set: tuple[SuppliedEvidence, ...],
                   expected: SessionKey) -> Resolution:
    """Bounded uniqueness in a caller-selected set, never global uniqueness.

    Exact duplicate triples collapse by content identity. Distinct observations
    with an identical key are ambiguous. Invalid or unresolved candidates
    prevent a positive uniqueness claim. This does not scan or open a store.
    """
    if (type(evidence_set) is not tuple or type(expected) is not SessionKey
            or len(evidence_set) > MAX_CANDIDATES
            or any(type(e) is not SuppliedEvidence for e in evidence_set)):
        return Resolution("REJECTED", "BATCH_LIMIT_OR_TYPE")
    if sum(len(e.reference) + len(e.envelope) + len(e.payload)
           for e in evidence_set) > MAX_BATCH_BYTES:
        return Resolution("REJECTED", "BATCH_BYTE_LIMIT")
    matches = {}
    for item in evidence_set:
        result = resolve_session(item, expected=expected)
        if result.status == "MISMATCH":
            continue
        if result.status != "CONTENT_MATCHED":
            return Resolution("UNRESOLVED", "CANDIDATE_SET_NOT_FULLY_RESOLVED")
        b = result.binding
        identity = (b.observation_id, b.payload_sha256_hex)
        previous = matches.get(identity)
        if previous is not None and previous != b:
            return Resolution("AMBIGUOUS", "CONTENT_IDENTITY_CONFLICT")
        matches[identity] = b
    if len(matches) > 1:
        return Resolution("AMBIGUOUS", "MULTIPLE_OBSERVATIONS_FOR_SESSION_KEY")
    if not matches:
        return Resolution("UNRESOLVED", "NO_MATCH_IN_SUPPLIED_SET")
    return Resolution("CONTENT_MATCHED", "UNIQUE_IN_SUPPLIED_SET", next(iter(matches.values())))
