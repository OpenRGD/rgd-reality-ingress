"""Host receive-time evidence; intentionally NOT a Chronograf TimeAtom."""
from __future__ import annotations

import time
from pathlib import Path


def host_clock_domain() -> dict:
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        boot_id = "unknown"
    return {
        "clock_domain_id_str": f"chronos.monotonic.boot:{boot_id}",
        "layer_enum_str": "CHRONOS",
        "clock_kind_enum_str": "MONOTONIC",
        "epoch_ref_str": f"linux-boot:{boot_id}",
        "timescale_enum_str": "MONOTONIC",
        "boot_id_str": boot_id,
    }


def source_receive_stamp(method: str, clock_domain: dict | None = None) -> dict:
    """Bracket monotonic observation with two wall-clock reads.

    The bracket measures only host clock-pair sampling span; it DOES NOT
    measure camera exposure time, USB delay, or Chronograf synchronization.
    """
    wall_before = time.time_ns()
    monotonic = time.monotonic_ns()
    wall_after = time.time_ns()
    return {
        "received_monotonic_ns": monotonic,
        "received_unix_estimate_ns": (wall_before + wall_after) // 2,
        "host_wall_pair_span_ns": max(0, wall_after - wall_before),
        "clock_domain_ref": clock_domain if clock_domain is not None else host_clock_domain(),
        "receive_timestamp_method": method,
        "source_time": None,
        "source_time_status_str": "UNKNOWN_NOT_EXPOSED_BY_SOURCE",
    }


def receive_stamp() -> dict:
    """Compatibility shim for original camera capture timestamp."""
    return source_receive_stamp(method="userspace_after_VideoCapture_read")


def derivation_stamp() -> dict:
    """Host processing-time sample, not a measurement of camera capture time."""
    wall_before = time.time_ns()
    mono = time.monotonic_ns()
    wall_after = time.time_ns()
    return {
        "recorded_monotonic_ns": mono,
        "recorded_unix_estimate_ns": (wall_before + wall_after) // 2,
        "host_wall_pair_span_ns": max(0, wall_after - wall_before),
        "clock_domain_ref": host_clock_domain(),
        "timestamp_method": "userspace_after_perception_inference",
    }
