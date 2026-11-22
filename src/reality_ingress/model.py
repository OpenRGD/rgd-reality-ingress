"""Explicitly experimental envelope, NOT an accepted canonical JSON Schema.

The published Agent Contracts 0.1.0 are a convergence candidate; the temporal
profile documents clock-domain responsibilities, not a finalized external
ObservationEnvelope JSON schema. This module is the adapter-side projection.
"""
from __future__ import annotations

import uuid
from typing import Any

SCHEMA_REF = "urn:openrgd:experimental:reality-ingress:observation-envelope:v0"
CONTRACT_BASIS = "OpenRGD Agent Contracts v0.1.0 Temporal/Chronon Profile (candidate)"


def observation_envelope(
    *,
    source_id: str,
    source_modality: str,
    reference_frame_id: str,
    sequence: int,
    payload_sha256: str,
    payload_ref: str,
    payload_media_type: str,
    payload_size_bytes: int,
    timestamp: dict[str, Any],
    representation: dict[str, Any],
) -> dict[str, Any]:
    if not source_id or not reference_frame_id:
        raise ValueError("source_id and reference_frame_id are required")
    if sequence < 0:
        raise ValueError("sequence must not be negative")
    if len(payload_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in payload_sha256):
        raise ValueError("sha256 must be 64 lowercase hex characters")

    return {
        "schema_ref_str": SCHEMA_REF,
        "contract_basis_str": CONTRACT_BASIS,
        "normative_bool": False,
        "observation_id_str": "obs_" + uuid.uuid4().hex,
        "source": {
            "source_id_str": source_id,
            "modality_str": source_modality,
            "reference_frame_id_str": reference_frame_id,
            "sample_sequence_uint": sequence,
        },
        "temporal_binding": {
            # Crucial: the OpenCV/V4L2 read does not provide a proven
            # hardware exposure timestamp here.
            "source_time": None,
            "source_time_status_str": "UNKNOWN_NOT_EXPOSED_BY_OPENCV",
            "received_monotonic_ns": timestamp["received_monotonic_ns"],
            "received_unix_estimate_ns": timestamp["received_unix_estimate_ns"],
            "host_wall_pair_span_ns": timestamp["host_wall_pair_span_ns"],
            "clock_domain_ref": timestamp["clock_domain_ref"],
            "validity_interval": None,
            "alignment_status_str": "NOT_RESOLVED_BY_CHRONOGRAF",
            "capture_to_receive_latency_ns": None,
        },
        "evidence": {
            "payload_ref_str": payload_ref,
            "payload_sha256_hex_str": payload_sha256,
            "payload_media_type_str": payload_media_type,
            "payload_size_bytes_uint": payload_size_bytes,
            "representation": representation,
        },
        "provenance": {
            "producer_str": "reality-ingress-python/0.1.0",
            "acquisition_path_str": "V4L2 -> OpenCV VideoCapture -> decoded frame",
            "derivation_str": "captured pixels re-encoded; not native UVC MJPEG bytes",
            "attestation_str": "none",
        },
    }
