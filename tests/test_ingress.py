import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from reality_ingress.consumers import agent_evidence_ref
from reality_ingress.evidence import EvidenceStore
from reality_ingress.timebase import receive_stamp


class RealityIngressTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = EvidenceStore(self.temp_dir.name)

    def record(self, data=b"synthetic-pixels-v1", sequence=1):
        return self.store.record(
            data=data,
            source_id="sensor.test.camera.001",
            modality="rgb",
            reference_frame_id="frame.test.camera.001",
            sequence=sequence,
            timestamp=receive_stamp(),
            media_type="application/octet-stream",
            representation={"kind_str": "synthetic_test_fixture"},
        )

    def test_payload_content_address_and_integrity(self):
        envelope = self.record()
        digest = hashlib.sha256(b"synthetic-pixels-v1").hexdigest()
        self.assertEqual(envelope["evidence"]["payload_sha256_hex_str"], digest)
        self.assertEqual(self.store.verify()["status"], "PASS")
        self.assertEqual(self.store.verify()["observation_count"], 1)

    def test_payload_deduplicated_without_rewriting_observations(self):
        a = self.record(sequence=1)
        b = self.record(sequence=2)
        self.assertNotEqual(a["observation_id_str"], b["observation_id_str"])
        self.assertEqual(a["evidence"]["payload_ref_str"], b["evidence"]["payload_ref_str"])
        self.assertEqual(self.store.verify()["unique_payload_count"], 1)

    def test_payload_tampering_detected(self):
        envelope = self.record()
        digest = envelope["evidence"]["payload_sha256_hex_str"]
        self.store._payload_path(digest).write_bytes(b"TAMPERED")
        check = self.store.verify()
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("hash mismatch", str(check["errors"]).lower())

    def test_no_agent_ownership_or_self_in_source(self):
        envelope = self.record()
        self.assertNotIn("agent_id", json.dumps(envelope))
        self.assertNotIn("SELF", json.dumps(envelope))
        self.assertNotIn("robot_owner", json.dumps(envelope))
        self.assertEqual(envelope["source"]["source_id_str"], "sensor.test.camera.001")

    def test_one_observation_referenced_by_ten_agents(self):
        envelope = self.record()
        obs_id = envelope["observation_id_str"]
        references = [agent_evidence_ref(f"robot_{i}", obs_id) for i in range(10)]
        self.assertEqual(len({r["agent_id_str"] for r in references}), 10)
        self.assertEqual({r["evidence_observation_id_str"] for r in references}, {obs_id})
        self.assertEqual(self.store.verify()["unique_payload_count"], 1)
        self.assertEqual(self.store.verify()["observation_count"], 1)

    def test_no_fake_hardware_or_global_time(self):
        envelope = self.record()
        t = envelope["temporal_binding"]
        self.assertIsNone(t["source_time"])
        self.assertIsNone(t["validity_interval"])
        self.assertIsNone(t["capture_to_receive_latency_ns"])
        self.assertEqual(t["alignment_status_str"], "NOT_RESOLVED_BY_CHRONOGRAF")
        self.assertEqual(t["clock_domain_ref"]["clock_kind_enum_str"], "MONOTONIC")
        self.assertGreater(t["received_monotonic_ns"], 0)

    def test_observation_is_write_once(self):
        envelope = self.record()
        obs_id = envelope["observation_id_str"]
        path = self.store.observations / (obs_id + ".json")
        old = path.read_bytes()
        self.assertEqual(self.store.get_observation(obs_id), envelope)
        self.assertEqual(path.read_bytes(), old)


if __name__ == "__main__":
    unittest.main()
