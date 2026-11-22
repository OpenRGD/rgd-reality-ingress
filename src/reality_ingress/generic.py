"""Experimental, agnostic JSONL sensor-sample intake.

No LeRobot/robot dependency, no actuation, no agent ID, no fabricated clock.
A sample is stamped by its producer at measurement availability, not import time.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from .evidence import EvidenceStore, IntegrityError, _atomic_create
from .model import CONTRACT_BASIS

SCHEMA_REF = "urn:openrgd:experimental:reality-ingress:generic-observation:v0"
SAMPLE_SCHEMA = "urn:openrgd:experimental:reality-ingress:source-sample:v0"
MEDIA_TYPE = "application/vnd.openrgd.experimental.sensor-sample+json"
MAX_SAMPLE_BYTES = 1_000_000


def canonical_json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validate_tree(value: Any, level: int = 0) -> None:
    if level > 32:
        raise ValueError("Sample nesting exceeds 32 levels")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite sensor value")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Payload object keys must be strings")
            _validate_tree(item, level + 1)
    elif isinstance(value, list):
        for item in value:
            _validate_tree(item, level + 1)
    elif value is None or type(value) in (str, int, float, bool):
        return
    else:
        raise ValueError("Non-JSON sensor value")


def validate_sample(row: dict[str, Any]) -> None:
    if not isinstance(row, dict) or row.get("schema_ref_str") != SAMPLE_SCHEMA:
        raise ValueError(f"Expected {SAMPLE_SCHEMA}")
    source = row.get("source")
    if not isinstance(source, dict):
        raise ValueError("Missing source")
    for key in ("source_id_str", "modality_str", "reference_frame_id_str"):
        value = source.get(key)
        if not isinstance(value, str) or not (0 < len(value) <= 256):
            raise ValueError(f"Invalid {key}")
    sequence = source.get("sample_sequence_uint")
    if type(sequence) is not int or sequence < 0:
        raise ValueError("Invalid sample sequence")
    stamp = row.get("temporal_binding")
    if not isinstance(stamp, dict):
        raise ValueError("Missing temporal_binding")
    for key in ("received_monotonic_ns", "received_unix_estimate_ns", "host_wall_pair_span_ns"):
        if type(stamp.get(key)) is not int or stamp[key] < 0:
            raise ValueError(f"Invalid {key}")
    domain = stamp.get("clock_domain_ref")
    if not isinstance(domain, dict):
        raise ValueError("Missing clock domain")
    if domain.get("clock_kind_enum_str") != "MONOTONIC":
        raise ValueError("This ingestion profile currently supports monotonic host stamps only")
    if not isinstance(domain.get("clock_domain_id_str"), str) or not domain["clock_domain_id_str"]:
        raise ValueError("Missing clock domain ID")
    if domain.get("boot_id_str") in (None, "", "unknown"):
        raise ValueError("A known boot ID is required for same-host time correlation")
    if stamp.get("source_time") is not None:
        raise ValueError("v0.4 does not yet accept claims about source-side measurement time")
    if stamp.get("source_time_status_str") != "UNKNOWN_NOT_EXPOSED_BY_SOURCE":
        raise ValueError("Source-side measurement time must be explicitly unknown")
    if "payload" not in row or not isinstance(row["payload"], dict):
        raise ValueError("Missing payload object")
    if not isinstance(row.get("producer_str"), str) or not row["producer_str"]:
        raise ValueError("Missing producer name")
    _validate_tree(row)
    if len(canonical_json(row)) > MAX_SAMPLE_BYTES:
        raise ValueError("Sample is too large")
    for forbidden in ("agent_id", "robot_owner", "relation_to_agent", "self_relation"):
        if forbidden in source or forbidden in row:
            raise ValueError(f"Source may not assert agent-relative field {forbidden}")


def envelope_from_sample(row: dict[str, Any], digest: str, payload_ref: str, byte_length: int) -> dict[str, Any]:
    stamp = row["temporal_binding"]
    domain = stamp["clock_domain_ref"]
    env = {
        "schema_ref_str": SCHEMA_REF,
        "contract_basis_str": CONTRACT_BASIS,
        "normative_bool": False,
        "source": dict(row["source"]),
        "temporal_binding": {
            "source_time": None,
            "source_time_status_str": "UNKNOWN_NOT_EXPOSED_BY_SOURCE",
            "received_monotonic_ns": stamp["received_monotonic_ns"],
            "received_unix_estimate_ns": stamp["received_unix_estimate_ns"],
            "host_wall_pair_span_ns": stamp["host_wall_pair_span_ns"],
            "clock_domain_ref": dict(domain),
            "validity_interval": None,
            "alignment_status_str": "NOT_RESOLVED_BY_CHRONOGRAF",
            "capture_to_receive_latency_ns": None,
        },
        "evidence": {
            "payload_ref_str": payload_ref,
            "payload_sha256_hex_str": digest,
            "payload_media_type_str": MEDIA_TYPE,
            "payload_size_bytes_uint": byte_length,
            "representation": {"kind_str": "canonicalized_source_json", "source_schema_ref_str": SAMPLE_SCHEMA},
        },
        "provenance": {
            "producer_str": row["producer_str"],
            "acquisition_path_str": "external source -> JSONL -> Reality Ingress",
            "derivation_str": "Parsed source sample serialized in deterministic JSON order; not raw transport bytes",
            "attestation_str": "none",
        },
    }
    env["observation_id_str"] = "obs_" + hashlib.sha256(canonical_json(env)).hexdigest()[:32]
    return env


def verify_generic_envelope(env: dict[str, Any]) -> None:
    if env.get("schema_ref_str") != SCHEMA_REF:
        raise IntegrityError("Not a generic observation")
    copy = dict(env)
    obs_id = copy.pop("observation_id_str", None)
    digest = hashlib.sha256(canonical_json(copy)).hexdigest()[:32]
    if obs_id != "obs_" + digest:
        raise IntegrityError("Generic observation envelope integrity mismatch")
    if env["evidence"]["payload_media_type_str"] != MEDIA_TYPE:
        raise IntegrityError("Generic observation media type mismatch")


def record_sample(store: EvidenceStore, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    validate_sample(row)
    payload = canonical_json(row)
    digest, ref = store.put_payload(payload)
    envelope = envelope_from_sample(row, digest, ref, len(payload))
    obs_id = envelope["observation_id_str"]
    path = store.observations / f"{obs_id}.json"
    encoded = json.dumps(envelope, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    created = _atomic_create(path, encoded)
    if not created and path.read_bytes() != encoded:
        raise IntegrityError("Conflicting existing observation ID")
    return envelope, created


def ingest_jsonl(store: EvidenceStore, path: str | Path) -> dict[str, Any]:
    """Streaming ingest; no reinterpretation of source timestamps at import."""
    input_path = Path(path).expanduser()
    processed, created, existing = 0, 0, 0
    with input_path.open("r", encoding="utf-8") as stream:
        for lineno, raw in enumerate(stream, 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite")))
                envelope, is_new = record_sample(store, row)
            except (ValueError, KeyError, TypeError, IntegrityError) as exc:
                raise ValueError(f"Line {lineno}: {exc}") from exc
            processed += 1
            created += bool(is_new)
            existing += not is_new
    return {
        "status": "INGESTED_NOT_CHRONOGRAF_ANCHORED",
        "processed": processed, "new_observations": created, "already_present": existing,
    }
