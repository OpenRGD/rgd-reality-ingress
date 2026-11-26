"""RI-A02B: new optional native integer profile and immutable registry update."""
from copy import deepcopy
import json
import unittest

from jsonschema import Draft202012Validator

from reality_ingress.interop_numeric import (
    NumericDomainError, MAX_U64, MAX_SAFE_JSON_NUMBER,
    require_u64, check_ref_integer_domain, fits_safe_json_number,
)
from scripts import check_compat_registry as registry

SNAPSHOT = "docs/compatibility/registry.snapshot-2026-11-26-cal-021-c.json"
CAL_HEAD = "646dbc05bcefd15942b25bb55b3c99096f0cccc9"


class NativeDomainTests(unittest.TestCase):
    def counters(self, value):
        return {"sample_sequence": value, "payload_size_bytes": value,
                "time": {"received_monotonic_ns": value}}

    def test_exact_native_limits(self):
        for n in (0, 1, 2**53-1, 2**53, 2**53+1, MAX_U64):
            with self.subTest(n=n):
                self.assertEqual(require_u64(n), n)
                ref = self.counters(n)
                before = deepcopy(ref)
                check_ref_integer_domain(ref)
                self.assertEqual(ref, before)

    def test_outside_native_domain(self):
        for n in (-1, 2**64, 2**100, True, False, 1.0, 1e3, "7", None):
            with self.subTest(n=n), self.assertRaises(NumericDomainError):
                require_u64(n)

    def test_all_three_fields_checked(self):
        for field in ("sample_sequence", "payload_size_bytes", "received_monotonic_ns"):
            ref = self.counters(0)
            owner = ref["time"] if field == "received_monotonic_ns" else ref
            owner[field] = 2**64
            with self.subTest(field=field), self.assertRaises(NumericDomainError):
                check_ref_integer_domain(ref)

    def test_missing_shape_is_not_numeric_acceptance(self):
        for ref in (None, {}, {"sample_sequence": 1, "payload_size_bytes": 1, "time": None}):
            with self.subTest(ref=ref), self.assertRaises(NumericDomainError):
                check_ref_integer_domain(ref)

    def test_lossless_native_not_binary64_transport(self):
        self.assertEqual(MAX_SAFE_JSON_NUMBER, 9007199254740991)
        self.assertTrue(fits_safe_json_number(MAX_SAFE_JSON_NUMBER))
        self.assertFalse(fits_safe_json_number(MAX_SAFE_JSON_NUMBER + 1))
        self.assertFalse(fits_safe_json_number(MAX_U64))
        # Advisory transport check does not truncate or invalidate native u64.
        self.assertEqual(require_u64(MAX_U64), MAX_U64)
        self.assertEqual(json.loads(json.dumps(MAX_SAFE_JSON_NUMBER+2)), MAX_SAFE_JSON_NUMBER+2)

    def test_no_retroactive_schema_change(self):
        schema = registry.load_json(registry.ROOT / registry.REF_PATH)
        for field in ("sample_sequence", "payload_size_bytes", "received_monotonic_ns"):
            node = schema["properties"]["time"]["properties"][field] if field == "received_monotonic_ns" else schema["properties"][field]
            self.assertNotIn("maximum", node)
            validator = Draft202012Validator(node)
            self.assertTrue(validator.is_valid(2**64))
            self.assertTrue(validator.is_valid(1.0))
            with self.subTest(field=field), self.assertRaises(NumericDomainError):
                require_u64(2**64)


class RegistrySupplementTests(unittest.TestCase):
    def test_additive_cal_scoped_snapshot(self):
        historical = registry.load_json(registry.ROOT / registry.REGISTRY)
        current = registry.load_json(registry.ROOT / SNAPSHOT)
        schema = registry.load_json(registry.ROOT / registry.SCHEMA)
        registry.validate_registry(historical, schema)
        registry.validate_registry(current, schema)
        self.assertEqual(registry.verify_files(current, registry.ROOT), 24)
        registry.verify_git_baseline(current, registry.ROOT)
        self.assertEqual(current["baseline"], historical["baseline"])
        self.assertEqual(current["snapshot_date"], "2026-11-26")
        self.assertGreater(current["snapshot_date"], historical["snapshot_date"])
        for old, new in zip(historical["targets"], current["targets"]):
            self.assertEqual(old["id"], new["id"])
            if old["id"] != "RI-H04":
                self.assertEqual(old, new)
                continue
            self.assertEqual(old["integrations"], new["integrations"][:-1])
            self.assertTrue(set(old["open_gates"]) <= set(new["open_gates"]))
            added = new["integrations"][-1]
            self.assertEqual(added["id"], "CAL-021-C")
            self.assertEqual(added["pull_request"], 9)
            self.assertEqual(added["commit"], CAL_HEAD)
            self.assertEqual(added["verification_kind"], "pinned_ri_implementation")
            self.assertIn("161318d2897d07d5628ef502cafba1c7c489fff0", added["scope"])
            self.assertTrue(any(c["run_id"] == 45806326568 and c["scope"] == "ri_conformance"
                                for c in added["checks"]))
            self.assertEqual(len(added["checks"]), 8)
        self.assertEqual(registry.summary(historical)["integration_records"], 9)
        self.assertEqual(registry.summary(current)["integration_records"], 10)
        self.assertEqual(registry.summary(current)["ci_records"], 23)
        self.assertEqual(registry.summary(current)["handoffs_received"], 7)


if __name__ == "__main__":
    unittest.main()
