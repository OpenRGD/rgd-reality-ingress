"""RI-INTEGRATION-01 candidate: read-only references for v0.4 evidence.

Never changes a legacy envelope, its observation ID or its content address.
Never opens devices, sends commands, timestamps data or creates Chronons.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .evidence import EvidenceStore, IntegrityError


_ID_RE = re.compile(r"obs_[0-9a-f]{32}\Z")
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_LEGACY_SCHEMAS = frozenset({
    "urn:openrgd:experimental:reality-ingress:observation-envelope:v0",
    "urn:openrgd:experimental:reality-ingress:generic-observation:v0",
})
_UNKNOWN_SOURCE_TIMES = frozenset({
    "UNKNOWN_NOT_EXPOSED_BY_OPENCV",
    "UNKNOWN_NOT_EXPOSED_BY_SOURCE",
})


def _string(value: Any, name: str, limit: int = 256) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= limit:
        raise ValueError(f"Invalid {name}")
    return value


def _integer(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"Invalid {name}")
    return value


def _build_ref(envelope: Mapping[str, Any], integrity_status: str) -> dict[str, Any]:
    """Project only fields supported by legacy v0.4; fail closed on missing data."""
    if not isinstance(envelope, Mapping) or envelope.get("schema_ref_str") not in _LEGACY_SCHEMAS:
        raise ValueError("Unsupported or unverified historical observation schema")
    if envelope.get("normative_bool") is not False:
        raise ValueError("Legacy observation must be explicitly non-normative")
    observation_id = _string(envelope.get("observation_id_str"), "observation_id")
    if not _ID_RE.fullmatch(observation_id):
        raise ValueError("Bad observation ID")
    source = envelope.get("source")
    evidence = envelope.get("evidence")
    stamp = envelope.get("temporal_binding")
    provenance = envelope.get("provenance")
    if not all(isinstance(x, Mapping) for x in (source, evidence, stamp, provenance)):
        raise ValueError("Missing source, evidence, temporal binding or provenance")
    if provenance.get("attestation_str") != "none":
        raise ValueError("Unexpected source attestation claim: requires reviewed contract")
    digest = _string(evidence.get("payload_sha256_hex_str"), "payload_sha256")
    if not _SHA_RE.fullmatch(digest):
        raise ValueError("Invalid payload digest")
    if stamp.get("source_time") is not None:
        raise ValueError("v0.4 projection cannot claim a verified source measurement time")
    if stamp.get("source_time_status_str") not in _UNKNOWN_SOURCE_TIMES:
        raise ValueError("Unexpected source time status")
    if stamp.get("alignment_status_str") != "NOT_RESOLVED_BY_CHRONOGRAF":
        raise ValueError("Chronograf binding requires an independently reviewed adapter")
    domain = stamp.get("clock_domain_ref")
    if not isinstance(domain, Mapping):
        raise ValueError("Missing clock domain")
    if domain.get("clock_kind_enum_str") != "MONOTONIC":
        raise ValueError("Only source-labelled monotonic receipt clocks supported")
    boot_id = domain.get("boot_id_str")
    if boot_id in ("unknown", "", None):
        boot_id = None
    elif not isinstance(boot_id, str):
        raise ValueError("Invalid boot ID")
    if integrity_status not in ("not_verified", "verified_local_hash"):
        raise ValueError("Unknown integrity status")
    return {
        "schema_version": "ri.consumer-observation-ref.v0.1-candidate",
        "observation_id": observation_id,
        "source_id": _string(source.get("source_id_str"), "source_id"),
        "modality": _string(source.get("modality_str"), "modality", 128),
        "reference_frame_id": _string(source.get("reference_frame_id_str"), "reference_frame_id"),
        "sample_sequence": _integer(source.get("sample_sequence_uint"), "sample_sequence"),
        "payload_sha256_hex": digest,
        "payload_media_type": _string(evidence.get("payload_media_type_str"), "payload_media_type", 128),
        "payload_size_bytes": _integer(evidence.get("payload_size_bytes_uint"), "payload_size_bytes"),
        "origin_status": "unknown",  # v0.4 content hashes do NOT authenticate physical provenance.
        "integrity_status": integrity_status,
        "source_verified": False,
        "robot_binding_verified": False,
        "history_committed": False,
        "actuation_enabled": False,
        "time": {
            "clock_domain_id": _string(domain.get("clock_domain_id_str"), "clock_domain_id"),
            "boot_id": boot_id,
            "received_monotonic_ns": _integer(stamp.get("received_monotonic_ns"), "received_monotonic_ns"),
            "source_time_status": "unknown",
            "source_measurement_time": None,
            "chronograf_anchor_ref": None,
        },
    }


def unverified_ref_from_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Read-only, untrusted metadata projection; NEVER claim that the hash was checked."""
    return _build_ref(envelope, "not_verified")


def verified_ref_from_store(store: EvidenceStore, observation_id: str) -> dict[str, Any]:
    """Expensive OFFLINE store-wide verification before returning a hash-verified ref.

    This does not attest the physical sensor or establish canonical time/history.
    Callers must apply separate read ACLs/retention controls before providing this
    metadata to a consumer, and separate authorization before serving media.
    """
    if not isinstance(store, EvidenceStore):
        raise TypeError("An explicit EvidenceStore is required")
    if not store.root.is_dir():
        raise IntegrityError("Evidence store does not exist")
    if not _ID_RE.fullmatch(_string(observation_id, "observation_id")):
        raise IntegrityError("Invalid observation ID")
    report = store.verify()
    if report.get("status") != "PASS":
        raise IntegrityError("Evidence store verification failed")
    envelope = store.get_observation(observation_id)
    return _build_ref(envelope, "verified_local_hash")
