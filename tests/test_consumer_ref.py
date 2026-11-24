"""Candidate RI-INTEGRATION-01 tests. No devices, motors, sockets or networks."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from reality_ingress.consumer_ref import (
    unverified_ref_from_envelope,
    verified_ref_from_store,
)
from reality_ingress.evidence import EvidenceStore, IntegrityError
from reality_ingress.generic import SAMPLE_SCHEMA, envelope_from_sample
from reality_ingress.timebase import receive_stamp


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts" / "consumer-observation-ref.v0.1-candidate.schema.json"


class ReadOnlyConsumerRefTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "evidence")
        self.raw = b"synthetic-camera-frame-contents"
        self.env = self.store.record(
            data=self.raw,
            source_id="source.synthetic.camera",
            modality="rgb",
            reference_frame_id="frame.camera.synthetic",
            sequence=1,
            timestamp=receive_stamp(),
            media_type="image/jpeg",
            representation={"kind_str": "reencoded_jpeg_synthetic"},
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_reference_projection_preserves_identity_and_never_claims_authority(self):
        before = copy.deepcopy(self.env)
        ref = unverified_ref_from_envelope(self.env)
        self.assertEqual(before, self.env)
        self.assertEqual(ref["observation_id"], self.env["observation_id_str"])
        self.assertEqual(ref["payload_sha256_hex"], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(ref["integrity_status"], "not_verified")
        self.assertEqual(ref["origin_status"], "unknown")
        self.assertIsNone(ref["time"]["chronograf_anchor_ref"])
        self.assertIsNone(ref["time"]["source_measurement_time"])
        self.assertFalse(ref["robot_binding_verified"])
        self.assertFalse(ref["source_verified"])
        self.assertFalse(ref["history_committed"])
        self.assertFalse(ref["actuation_enabled"])
        self.assertNotIn("payload_ref_str", ref)
        self.assertNotIn("robot_instance_id", ref)

    def test_offline_verification_may_claim_only_local_hash(self):
        ref = verified_ref_from_store(self.store, self.env["observation_id_str"])
        self.assertEqual(ref["integrity_status"], "verified_local_hash")
        self.assertFalse(ref["source_verified"])
        self.assertFalse(ref["history_committed"])

    def test_corrupt_payload_rejected(self):
        digest = self.env["evidence"]["payload_sha256_hex_str"]
        self.store._payload_path(digest).write_bytes(b"tampered")
        with self.assertRaises(IntegrityError):
            verified_ref_from_store(self.store, self.env["observation_id_str"])

    def test_fabricated_source_or_chronograf_time_rejected(self):
        for path, fake in (
            (("temporal_binding", "source_time"), "2026-01-01T00:00:00Z"),
            (("temporal_binding", "alignment_status_str"), "VERIFIED"),
            (("provenance", "attestation_str"), "trusted"),
            (("source", "sample_sequence_uint"), -1),
        ):
            broken = copy.deepcopy(self.env)
            broken[path[0]][path[1]] = fake
            with self.subTest(path=path), self.assertRaises(ValueError):
                unverified_ref_from_envelope(broken)

    def test_missing_observation_or_bad_digest_rejected(self):
        wrong = copy.deepcopy(self.env)
        wrong["observation_id_str"] = "obs_fake"
        with self.assertRaises(ValueError):
            unverified_ref_from_envelope(wrong)
        wrong = copy.deepcopy(self.env)
        wrong["evidence"]["payload_sha256_hex_str"] = "0" * 63
        with self.assertRaises(ValueError):
            unverified_ref_from_envelope(wrong)

    def test_generic_legacy_envelope_supported_without_rekeying(self):
        stamp = receive_stamp()
        row = {
            "schema_ref_str": SAMPLE_SCHEMA,
            "producer_str": "synthetic.offline.test",
            "source": {
                "source_id_str": "source.synthetic.imu",
                "modality_str": "joint_state",
                "reference_frame_id_str": "frame.synthetic.arm",
                "sample_sequence_uint": 7,
            },
            "temporal_binding": stamp,
            "payload": {"measurements": {}},
        }
        env = envelope_from_sample(row, "0" * 64, "payloads/00/test.bin", 14)
        ref = unverified_ref_from_envelope(env)
        self.assertEqual(ref["observation_id"], env["observation_id_str"])
        self.assertEqual(ref["modality"], "joint_state")
        self.assertEqual(ref["sample_sequence"], 7)
        self.assertEqual(ref["integrity_status"], "not_verified")

    def test_schema_contract_matches_projection_and_rejects_false_authority(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema optional; candidate-contracts CI installs it explicitly")
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        example = verified_ref_from_store(self.store, self.env["observation_id_str"])
        self.assertEqual(list(validator.iter_errors(example)), [])
        for change in (
            {"source_verified": True},
            {"robot_binding_verified": True},
            {"actuation_enabled": True},
            {"history_committed": True},
            {"observation_id": "obs_invalid"},
            {"time": {**example["time"], "chronograf_anchor_ref": "fake"}},
            {"unexpected_field": "payload path must not leak"},
        ):
            candidate = dict(example, **change)
            with self.subTest(change=change):
                self.assertTrue(list(validator.iter_errors(candidate)))


if __name__ == "__main__":
    unittest.main()
