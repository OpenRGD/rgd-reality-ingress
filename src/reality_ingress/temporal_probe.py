"""Only local same-boot *receipt-time* pairing. NEVER claims global/exposure sync."""
from __future__ import annotations

import bisect
import json
from pathlib import Path
from typing import Any

from .evidence import EvidenceStore


def temporal_probe(
    store: EvidenceStore, *, left_modality: str = "rgb", right_modality: str = "joint_state",
    max_offset_ms: float = 100.0, max_pairs: int = 500,
) -> dict[str, Any]:
    if not (0 < max_offset_ms <= 10_000):
        raise ValueError("max_offset_ms must be in (0, 10000]")
    if max_pairs <= 0:
        raise ValueError("max_pairs must be positive")

    check = store.verify()
    if check["status"] != "PASS":
        raise ValueError("The evidence store must verify PASS before temporal correlation")
    streams: dict[str, dict[str, list[tuple[int, str]]]] = {}
    for p in sorted(store.observations.glob("obs_*.json")):
        env = json.loads(p.read_text(encoding="utf-8"))
        modality = env["source"]["modality_str"]
        if modality not in (left_modality, right_modality):
            continue
        binding = env["temporal_binding"]
        domain = binding.get("clock_domain_ref", {})
        domain_id = domain.get("clock_domain_id_str")
        boot_id = domain.get("boot_id_str")
        if domain.get("clock_kind_enum_str") != "MONOTONIC" or not domain_id or boot_id in (None, "", "unknown"):
            continue
        key = domain_id + "|" + boot_id
        streams.setdefault(modality, {}).setdefault(key, []).append(
            (binding["received_monotonic_ns"], env["observation_id_str"])
        )
    left_all = streams.get(left_modality, {})
    right_all = streams.get(right_modality, {})
    pairs = []
    left_count = sum(map(len, left_all.values()))
    right_count = sum(map(len, right_all.values()))
    eligible_left = 0
    for domain, left in sorted(left_all.items()):
        if domain not in right_all:
            continue
        right = sorted(right_all[domain])
        stamps = [r[0] for r in right]
        for lt, lid in sorted(left):
            eligible_left += 1
            idx = bisect.bisect_left(stamps, lt)
            options = []
            for k in (idx - 1, idx):
                if 0 <= k < len(right):
                    rt, rid = right[k]
                    options.append((abs(rt - lt), rt, rid))
            if not options:
                continue
            diff, rt, rid = min(options)
            if diff > round(max_offset_ms * 1_000_000):
                continue
            pairs.append({
                "left_observation_id_str": lid,
                "right_observation_id_str": rid,
                "right_minus_left_received_ns": rt - lt,
                "absolute_receipt_offset_ms": round(diff / 1_000_000, 3),
                "clock_domain_instance_str": domain,
                "semantics_str": "HOST_USERSPACE_RECEIPT_TIME_PROXIMITY_ONLY",
            })
            if len(pairs) >= max_pairs:
                break
        if len(pairs) >= max_pairs:
            break
    return {
        "status": "LOCAL_RECEIPT_TIME_ONLY_NOT_CHRONOGRAF",
        "left_modality": left_modality,
        "right_modality": right_modality,
        "left_count": left_count, "right_count": right_count,
        "eligible_same_boot_left_count": eligible_left,
        "pair_count": len(pairs),
        "max_offset_ms": max_offset_ms,
        "pairs": pairs,
        "limitations": [
            "Not camera exposure timestamps or robot sensor sampling instants",
            "No time uncertainty bound for end-to-end latency",
            "No global Chronograf anchor or verified cross-host synchronization",
            "Nearest receipt-time alignment is diagnostic, not body kinematics or causality",
        ],
    }
