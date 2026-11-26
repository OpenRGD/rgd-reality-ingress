"""Cross-language representation tests with CAL's real pinned Rust fixture.

Only synthetic refs; numeric boundary variants are not real observations.
No calibration/acquisition or A02 session acceptance is implied.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from jsonschema import Draft202012Validator
from reality_ingress.evidence import EvidenceStore
from reality_ingress.consumer_ref import verified_ref_from_store
from reality_ingress.timebase import receive_stamp
from reality_ingress.interop_numeric import (
    MAX_U64, MAX_SAFE_JSON_NUMBER, check_ref_integer_domain, NumericDomainError,
)

ROOT = Path(__file__).resolve().parents[1]
CAL = Path(os.environ["CAL_CHECKOUT"])
PROBE = Path(os.environ["CAL_PROBE"])
REF_SCHEMA = json.loads((ROOT / "contracts/consumer-observation-ref.v0.1-candidate.schema.json").read_text())
CAL_SCHEMA = json.loads((CAL / "contracts/ri-calibration-association.v0.1-candidate.schema.json").read_text())


class CalExchangeTests(unittest.TestCase):
    def test_actual_rust_profile_agrees_with_native_counter_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "store")
            envelope = store.record(
                data=b"synthetic frame, not real media", source_id="source.synthetic.camera",
                modality="rgb", reference_frame_id="frame.camera.synthetic", sequence=1,
                timestamp=receive_stamp(), media_type="image/jpeg",
                representation={"kind_str": "synthetic_not_physical"},
            )
            original = verified_ref_from_store(store, envelope["observation_id_str"])
        ri_validator = Draft202012Validator(REF_SCHEMA)
        cal_validator = Draft202012Validator(CAL_SCHEMA)
        Draft202012Validator.check_schema(REF_SCHEMA)
        Draft202012Validator.check_schema(CAL_SCHEMA)
        variants = {"actual_ri_projection": original}
        expected = {"actual_ri_projection": True}
        for field in ("sample_sequence", "payload_size_bytes", "received_monotonic_ns"):
            for label, value, allowed in (
                ("zero", 0, True), ("above_js_safe", MAX_SAFE_JSON_NUMBER + 2, True),
                ("max", MAX_U64, True), ("overflow", MAX_U64 + 1, False),
                ("negative", -1, False), ("float", 1.0, False),
                ("bool", True, False), ("string", "1", False),
            ):
                ref = copy.deepcopy(original)
                target = ref["time"] if field == "received_monotonic_ns" else ref
                target[field] = value
                name = f"{field}_{label}"
                variants[name], expected[name] = ref, allowed
                if label in ("overflow", "float"):
                    self.assertTrue(ri_validator.is_valid(ref))
                if allowed:
                    check_ref_integer_domain(ref)
                else:
                    with self.assertRaises(NumericDomainError):
                        check_ref_integer_domain(ref)
        unicode_ref = copy.deepcopy(original)
        unicode_ref["source_id"] = "é" * 256
        unicode_ref["time"]["boot_id"] = "é" * 128
        variants["unicode_boundary"] = unicode_ref
        expected["unicode_boundary"] = True
        invalid_unicode = copy.deepcopy(unicode_ref)
        invalid_unicode["source_id"] += "é"
        variants["unicode_overflow"] = invalid_unicode
        expected["unicode_overflow"] = False
        self.assertTrue(ri_validator.is_valid(unicode_ref))
        self.assertFalse(ri_validator.is_valid(invalid_unicode))
        result = json.loads(subprocess.check_output(
            [str(PROBE)], input=json.dumps(variants, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            timeout=60,
        ))["ri"]
        self.assertEqual(set(result), set(variants))
        count = 0
        for name, ref in variants.items():
            with self.subTest(name=name):
                self.assertIs(result[name]["accepted"], expected[name])
                if not expected[name]:
                    self.assertEqual(result[name], {"accepted": False})
                    continue
                ri_validator.validate(ref)
                for kind in ("experimental", "sealed", "expired", "missing"):
                    sidecar = result[name][kind]
                    cal_validator.validate(sidecar)
                    ri_validator.validate(sidecar["observation_ref"])
                    self.assertEqual(sidecar["observation_ref"], ref)
                    self.assertFalse(sidecar["depth_consumer"]["metric_depth_allowed"])
                    count += 1
        print(f"CAL pinned Rust probe: {len(variants)} synthetic cases, {count} validated sidecars; no session/physical authority")


if __name__ == "__main__":
    unittest.main()
