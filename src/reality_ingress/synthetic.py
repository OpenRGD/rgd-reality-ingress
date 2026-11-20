"""Test-only synthetic source. Does not claim to sample a physical robot."""
from __future__ import annotations

import json
from pathlib import Path
from .generic import SAMPLE_SCHEMA
from .timebase import source_receive_stamp


def make_synthetic_jsonl(path: str | Path, count: int = 10) -> dict:
    path = Path(path).expanduser()
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        for i in range(count):
            f.write(json.dumps({
                "schema_ref_str": SAMPLE_SCHEMA,
                "producer_str": "openrgd-synthetic-fixture/no-real-hardware",
                "source": {
                    "source_id_str": "fixture.generic.body",
                    "modality_str": "joint_state",
                    "reference_frame_id_str": "frame.fixture.body",
                    "sample_sequence_uint": i,
                },
                "temporal_binding": source_receive_stamp("userspace_synthetic_fixture"),
                "payload": {"measurements": {
                    "joint_a.pos": {"value": float(i) * 0.1, "unit_str": "SOURCE_NATIVE_UNSPECIFIED"},
                    "joint_b.pos": {"value": -float(i) * 0.1, "unit_str": "SOURCE_NATIVE_UNSPECIFIED"},
                }},
            }, sort_keys=True) + "\n")
    return {"status": "SYNTHETIC_FIXTURE_NOT_PHYSICAL_MEASUREMENT", "samples": count, "file": str(path)}


def make_synthetic_pair_fixture(out: str | Path, count: int = 5) -> dict:
    """Exercise *simulated* multi-source pairing. NEVER physical camera/robot evidence."""
    from .evidence import EvidenceStore
    from .generic import record_sample
    if not (1 <= count <= 100):
        raise ValueError("Fixture count must be 1..100")
    store = EvidenceStore(out)
    if store.verify()["status"] != "EMPTY":
        raise ValueError("Refusing to mix synthetic fixture with existing evidence")
    base_stamp = source_receive_stamp("synthetic_camera_receipt")
    for i in range(count):
        stamp = dict(base_stamp)
        stamp["received_monotonic_ns"] = base_stamp["received_monotonic_ns"] + i * 100_000_000
        stamp["received_unix_estimate_ns"] = base_stamp["received_unix_estimate_ns"] + i * 100_000_000
        store.record(
            data=(f"NOT_A_REAL_IMAGE_{i}").encode("utf-8"),
            source_id="fixture.synthetic_camera", modality="rgb",
            reference_frame_id="frame.fixture.camera", sequence=i,
            timestamp=stamp, media_type="application/octet-stream",
            representation={"kind_str": "synthetic_not_an_image"},
        )
        stamp2 = dict(stamp)
        stamp2["received_monotonic_ns"] += 3_000_000  # simulated +3ms
        row = {
            "schema_ref_str": SAMPLE_SCHEMA,
            "producer_str": "synthetic_fixture/no_physical_robot",
            "source": {
                "source_id_str": "fixture.synthetic_body", "modality_str": "joint_state",
                "reference_frame_id_str": "frame.fixture.body", "sample_sequence_uint": i,
            },
            "temporal_binding": stamp2,
            "payload": {"measurements": {"joint_a.pos": {
                "value": i * 0.1, "unit_str": "SOURCE_NATIVE_UNSPECIFIED"}}},
        }
        record_sample(store, row)
    return {
        "status": "SYNTHETIC_PAIR_FIXTURE_NO_REAL_CAMERA_NO_REAL_ROBOT",
        "count_per_modality": count,
        "store": str(store.root),
    }
