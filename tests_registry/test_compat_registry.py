"""Offline engineering registry tests; no remote CI, hardware or authority."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts import check_compat_registry as registry


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = registry.load_json(registry.ROOT / registry.REGISTRY)
        cls.schema = registry.load_json(registry.ROOT / registry.SCHEMA)

    def validate(self, doc):
        registry.validate_registry(doc, self.schema)

    def changed(self):
        return copy.deepcopy(self.doc)

    def entry(self, doc, target_id):
        return next(t for t in doc["targets"] if t["id"] == target_id)["integrations"][0]

    def test_valid_snapshot(self):
        self.validate(self.doc)
        result = registry.summary(self.doc)
        self.assertEqual(result["handoffs_received"], 7)
        self.assertEqual(result["handoffs_total"], 10)
        self.assertEqual(result["integration_records"], 9)
        self.assertEqual(result["ci_records"], 15)
        self.assertFalse(result["remote_ci_reexecuted"])

    def test_frozen_bytes_and_complete_git_inventory(self):
        self.assertEqual(registry.verify_files(self.doc, registry.ROOT), 24)
        registry.verify_git_baseline(self.doc, registry.ROOT)

    def test_authority_claims_rejected(self):
        for flag in ("normative", "runtime_authority", "physical_commissioning"):
            doc = self.changed()
            doc[flag] = True
            with self.subTest(flag=flag), self.assertRaises(registry.RegistryError):
                self.validate(doc)

    def test_duplicate_targets(self):
        doc = self.changed()
        doc["targets"][0] = copy.deepcopy(doc["targets"][1])
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)

    def test_pending_target_with_return_rejected(self):
        doc = self.changed()
        doc["targets"][0]["integrations"] = copy.deepcopy(doc["targets"][1]["integrations"])
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)

    def test_received_without_return_rejected(self):
        doc = self.changed()
        doc["targets"][1]["integrations"] = []
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)

    def test_metadata_cannot_claim_implementation_ci(self):
        doc = self.changed()
        entry = self.entry(doc, "RI-H03")
        entry["checks"][0]["scope"] = "ri_conformance"
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)

    def test_documentary_cannot_claim_ci(self):
        doc = self.changed()
        entry = self.entry(doc, "RI-H08")
        entry["checks"] = [copy.deepcopy(self.entry(doc, "RI-H02")["checks"][0])]
        entry["checks"][0]["tested_commit"] = entry["commit"]
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)

    def test_documentary_cannot_be_promoted(self):
        doc = self.changed()
        next(t for t in doc["targets"] if t["id"] == "RI-H08")["status"] = "candidate_compatible"
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)

    def test_ci_head_mismatch(self):
        doc = self.changed()
        self.entry(doc, "RI-H02")["checks"][0]["tested_commit"] = "0" * 40
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)

    def test_missing_success_in_claimed_scope(self):
        doc = self.changed()
        self.entry(doc, "RI-H02")["checks"][0]["conclusion"] = "failure"
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)

    def test_duplicate_owner_pr(self):
        doc = self.changed()
        e = copy.deepcopy(self.entry(doc, "RI-H02"))
        e["id"] = "DUPLICATE-PR"
        e["return_comment_id"] += 100
        doc["targets"][1]["integrations"].append(e)
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)

    def test_duplicate_ci_record(self):
        doc = self.changed()
        e = self.entry(doc, "RI-H02")
        e["checks"].append(copy.deepcopy(e["checks"][0]))
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)

    def test_unsafe_path(self):
        doc = self.changed()
        self.entry(doc, "RI-H02")["artifacts"][0]["path"] = "../outside"
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)

    def test_repinned_schema_rejected(self):
        doc = self.changed()
        doc["baseline"]["schema_git_blob_sha1"] = "0" * 40
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)

    def test_incomplete_frozen_inventory_detected(self):
        doc = self.changed()
        doc["baseline"]["frozen_files"] = [
            f for f in doc["baseline"]["frozen_files"] if f["path"] != "src/reality_ingress/model.py"
        ]
        with self.assertRaises(registry.RegistryError):
            registry.verify_git_baseline(doc, registry.ROOT)

    def test_changed_frozen_pin_detected(self):
        doc = self.changed()
        doc["baseline"]["frozen_files"][0]["git_blob_sha1"] = "0" * 40
        with self.assertRaises(registry.RegistryError):
            registry.verify_files(doc, registry.ROOT)

    def test_bytes_changed_missing_and_symlink(self):
        data = b"original\n"
        doc = {"baseline": {"frozen_files": [
            {"path": "pyproject.toml", "git_blob_sha1": registry.git_blob_sha1(data)}
        ]}}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "pyproject.toml"
            path.write_bytes(data)
            self.assertEqual(registry.verify_files(doc, root), 1)
            path.write_bytes(b"changed\n")
            with self.assertRaises(registry.RegistryError):
                registry.verify_files(doc, root)
            path.unlink()
            with self.assertRaises(registry.RegistryError):
                registry.verify_files(doc, root)
            target = root / "other"
            target.write_bytes(data)
            path.symlink_to(target)
            with self.assertRaises(registry.RegistryError):
                registry.verify_files(doc, root)

    def test_duplicate_json_and_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
                p.write_text(raw, encoding="utf-8")
                with self.subTest(raw=raw), self.assertRaises(registry.RegistryError):
                    registry.load_json(p)

    def test_invalid_date_and_unknown_field(self):
        doc = self.changed()
        doc["snapshot_date"] = "2026-02-30"
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)
        doc = self.changed()
        doc["source_verified"] = True
        with self.assertRaises(registry.RegistryError):
            self.validate(doc)


if __name__ == "__main__":
    unittest.main()
