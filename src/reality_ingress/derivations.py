"""Append-only, independently content-committed perception derivations.

This is an EXPERIMENTAL adapter-side record, not a canonical ChrononRelation,
not a MemoryProjection, and not an accepted OpenRGD schema.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .evidence import EvidenceStore, IntegrityError, _atomic_create
from .timebase import derivation_stamp

SCHEMA_REF = "urn:openrgd:experimental:reality-ingress:perception-derivation:v0"
DERIVATION_ID_RE = re.compile(r"^der_[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_bytes(obj: dict[str, Any]) -> bytes:
    """Local JSON commitment format only, not final JCS/CBOR canonicalization."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_detections(detections: list[dict[str, Any]]) -> None:
    for detection in detections:
        label = detection["class_label_str"]
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Class label must be nonempty")
        if label.casefold() == "self":
            raise ValueError("SELF is agent-relative; it cannot be a detector label")
        confidence = detection["confidence_float"]
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("Confidence must be in [0, 1]")
        box = detection["bbox_xyxy_normalized_arr"]
        if len(box) != 4 or any(not isinstance(x, (int, float)) or not 0 <= x <= 1 for x in box):
            raise ValueError("Bounding box must have four finite normalized coordinates")
        if box[0] > box[2] or box[1] > box[3]:
            raise ValueError("Invalid bounding box extent")


class DerivationStore:
    def __init__(self, evidence_store: EvidenceStore):
        self.evidence_store = evidence_store
        self.root = evidence_store.root / "derivations"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, derivation_id: str) -> Path:
        if not DERIVATION_ID_RE.fullmatch(derivation_id):
            raise IntegrityError("Invalid derivation ID")
        return self.root / f"{derivation_id}.json"

    def create(
        self,
        *,
        observation_id: str,
        processor: dict[str, Any],
        detections: list[dict[str, Any]],
        inference_started_monotonic_ns: int | None = None,
    ) -> dict[str, Any]:
        # Verify the referenced image BEFORE creating any derived claim.
        original_path = self.evidence_store.observations / f"{observation_id}.json"
        envelope = self.evidence_store.get_observation(observation_id)
        original_bytes = original_path.read_bytes()
        payload_meta = envelope["evidence"]
        digest = payload_meta["payload_sha256_hex_str"]
        if not SHA256_RE.fullmatch(digest):
            raise IntegrityError("Invalid observation payload digest")
        payload = self.evidence_store._payload_path(digest).read_bytes()
        if sha256(payload) != digest or len(payload) != payload_meta["payload_size_bytes_uint"]:
            raise IntegrityError("Source evidence payload integrity mismatch")
        if payload_meta["payload_ref_str"] != str(self.evidence_store._payload_path(digest).relative_to(self.evidence_store.root)):
            raise IntegrityError("Source evidence noncanonical payload reference")
        if payload_meta["payload_media_type_str"] != "image/jpeg":
            raise ValueError("Only stored image/jpeg observations are supported by v0.2")
        if "agent_id" in processor or "self" in processor:
            raise ValueError("Processor must not define agent ownership or SELF")
        validate_detections(detections)
        stamp = derivation_stamp()
        body = {
            "schema_ref_str": SCHEMA_REF,
            "normative_bool": False,
            "derived_from": {
                "observation_id_str": observation_id,
                "observation_envelope_sha256_hex_str": sha256(original_bytes),
                "payload_sha256_hex_str": digest,
            },
            "processor": processor,
            "temporal_binding": {
                "derived_at_monotonic_ns": stamp["recorded_monotonic_ns"],
                "derived_at_unix_estimate_ns": stamp["recorded_unix_estimate_ns"],
                "host_wall_pair_span_ns": stamp["host_wall_pair_span_ns"],
                "clock_domain_ref": stamp["clock_domain_ref"],
                "source_observed_at_status_str": envelope["temporal_binding"].get("source_time_status_str", "UNKNOWN"),
                "chronograf_alignment_status_str": "NOT_RESOLVED_BY_CHRONOGRAF",
                "inference_started_monotonic_ns": inference_started_monotonic_ns,
            },
            "interpretation": {
                "kind_str": "object_detections_2d",
                "detections": detections,
                "object_count_uint": len(detections),
            },
            "provenance": {
                "producer_str": "reality-ingress-python/0.2.0",
                "derivation_method_str": "inference_on_immutable_stored_jpeg",
                "validation_scope_str": "local_content_and_reference_integrity_only",
                "attestation_str": "none",
            },
        }
        derivation_id = "der_" + sha256(canonical_bytes(body))
        record = {"derivation_id_str": derivation_id, **body}
        path = self._path(derivation_id)
        if not _atomic_create(path, json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"):
            raise IntegrityError("Derivation ID already exists")
        return record

    def find_existing(self, observation_id: str, processing_signature: str) -> bool:
        """Optional idempotency hint. Full verifier still checks every record."""
        for path in self.root.glob("der_*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if (record["derived_from"]["observation_id_str"] == observation_id
                    and record["processor"].get("processing_signature_sha256_hex_str") == processing_signature):
                    return True
            except (ValueError, OSError, KeyError):
                continue
        return False

    def verify(self) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        paths = sorted(self.root.glob("der_*.json"))
        verified_sources: set[str] = set()
        for path in paths:
            try:
                record = json.loads(path.read_bytes())
                identifier = record.pop("derivation_id_str")
                if path.name != f"{identifier}.json" or not DERIVATION_ID_RE.fullmatch(identifier):
                    raise IntegrityError("Derivation filename/ID mismatch")
                if sha256(canonical_bytes(record)) != identifier[4:]:
                    raise IntegrityError("Derivation content hash mismatch")
                if record.get("schema_ref_str") != SCHEMA_REF:
                    raise IntegrityError("Unknown derivation schema")
                ref = record["derived_from"]
                obs_id = ref["observation_id_str"]
                source_path = self.evidence_store.observations / f"{obs_id}.json"
                envelope = self.evidence_store.get_observation(obs_id)
                if sha256(source_path.read_bytes()) != ref["observation_envelope_sha256_hex_str"]:
                    raise IntegrityError("Source observation envelope modified")
                if envelope["evidence"]["payload_sha256_hex_str"] != ref["payload_sha256_hex_str"]:
                    raise IntegrityError("Source observation payload reference changed")
                validate_detections(record["interpretation"]["detections"])
                if record["interpretation"]["object_count_uint"] != len(record["interpretation"]["detections"]):
                    raise IntegrityError("Detection count mismatch")
                verified_sources.add(obs_id)
            except (ValueError, KeyError, OSError, IntegrityError, TypeError) as exc:
                errors.append({"derivation_file": path.name, "error": str(exc)})
        return {
            "status": "PASS" if not errors else "FAIL",
            "derivation_count": len(paths),
            "referenced_observation_count": len(verified_sources),
            "derivation_errors": errors,
        }
