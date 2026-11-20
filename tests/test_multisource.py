import copy
import json
import tempfile
import unittest
from pathlib import Path

from reality_ingress.evidence import EvidenceStore
from reality_ingress.generic import SAMPLE_SCHEMA, ingest_jsonl, record_sample
from reality_ingress.synthetic import make_synthetic_jsonl, make_synthetic_pair_fixture
from reality_ingress.telemetry_hook import TelemetryJSONL
from reality_ingress.temporal_probe import temporal_probe
from reality_ingress.timebase import receive_stamp, source_receive_stamp


class GenericMultiSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = EvidenceStore(self.root / "evidence")

    def row(self, stamp=None):
        return {
            "schema_ref_str": SAMPLE_SCHEMA,
            "producer_str": "test-readonly-producer",
            "source": {
                "source_id_str": "sensor.test.joint", "modality_str": "joint_state",
                "reference_frame_id_str": "frame.test.robot", "sample_sequence_uint": 1,
            },
            "temporal_binding": stamp or source_receive_stamp("test_sample_after_read"),
            "payload": {"measurements": {"x.pos": {"value": 1.0, "unit_str": "SOURCE_NATIVE_UNSPECIFIED"}}},
        }

    def test_generic_payload_record_integrity(self):
        env, is_new = record_sample(self.store, self.row())
        self.assertTrue(is_new)
        self.assertEqual(self.store.verify()["status"], "PASS")
        self.assertEqual(env["source"]["modality_str"], "joint_state")
        self.assertEqual(env["temporal_binding"]["alignment_status_str"], "NOT_RESOLVED_BY_CHRONOGRAF")
        self.assertIsNone(env["temporal_binding"]["source_time"])

    def test_ingest_idempotency(self):
        file = self.root / "samples.jsonl"
        make_synthetic_jsonl(file, count=4)
        result = ingest_jsonl(self.store, file)
        self.assertEqual(result["new_observations"], 4)
        result2 = ingest_jsonl(self.store, file)
        self.assertEqual(result2["new_observations"], 0)
        self.assertEqual(result2["already_present"], 4)
        self.assertEqual(self.store.verify()["observation_count"], 4)

    def test_rewrite_generic_envelope_fails_verification(self):
        env, _ = record_sample(self.store, self.row())
        path = self.store.observations / (env["observation_id_str"] + ".json")
        other = json.loads(path.read_text())
        other["source"]["source_id_str"] = "forged_source"
        path.write_text(json.dumps(other))
        check = self.store.verify()
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("integrity mismatch", str(check["errors"]).lower())

    def test_generic_payload_corruption(self):
        env, _ = record_sample(self.store, self.row())
        path = self.store._payload_path(env["evidence"]["payload_sha256_hex_str"])
        path.write_bytes(b"edited")
        self.assertEqual(self.store.verify()["status"], "FAIL")

    def test_reject_fabricated_source_stamp_and_unknown_clock(self):
        row = self.row()
        row["temporal_binding"]["source_time"] = 100
        with self.assertRaises(ValueError):
            record_sample(self.store, row)
        row = self.row()
        row["temporal_binding"]["clock_domain_ref"]["boot_id_str"] = "unknown"
        with self.assertRaises(ValueError):
            record_sample(self.store, row)

    def test_reject_nonfinite_and_agent_relation_at_source(self):
        row = self.row()
        row["payload"]["measurements"]["x.pos"]["value"] = float("nan")
        with self.assertRaises(ValueError):
            record_sample(self.store, row)
        row = self.row()
        row["agent_id"] = "robot_1"
        with self.assertRaises(ValueError):
            record_sample(self.store, row)

    def test_same_boot_receipt_pair_and_offset(self):
        stamp = receive_stamp()
        self.store.record(data=b"image_evidence", source_id="camera", modality="rgb",
                          reference_frame_id="camera_frame", sequence=1,
                          timestamp=stamp, media_type="application/octet-stream",
                          representation={"kind_str": "test"})
        stamp2 = source_receive_stamp("test_robot_read")
        stamp2["received_monotonic_ns"] = stamp["received_monotonic_ns"] + 5_000_000
        record_sample(self.store, self.row(stamp=stamp2))
        report = temporal_probe(self.store, max_offset_ms=10)
        self.assertEqual(report["pair_count"], 1)
        self.assertEqual(report["pairs"][0]["right_minus_left_received_ns"], 5_000_000)
        self.assertEqual(report["pairs"][0]["semantics_str"], "HOST_USERSPACE_RECEIPT_TIME_PROXIMITY_ONLY")

    def test_different_boot_does_not_pair(self):
        stamp = receive_stamp()
        self.store.record(data=b"image", source_id="camera", modality="rgb",
                          reference_frame_id="frame.cam", sequence=1,
                          timestamp=stamp, media_type="application/octet-stream",
                          representation={})
        later = source_receive_stamp("test_robot_read")
        later["received_monotonic_ns"] = stamp["received_monotonic_ns"]
        later["clock_domain_ref"] = copy.deepcopy(later["clock_domain_ref"])
        later["clock_domain_ref"]["boot_id_str"] = "other-boot-id"
        later["clock_domain_ref"]["clock_domain_id_str"] = "chronos.monotonic.boot:other-boot-id"
        record_sample(self.store, self.row(stamp=later))
        report = temporal_probe(self.store, max_offset_ms=10)
        self.assertEqual(report["pair_count"], 0)
        self.assertEqual(report["eligible_same_boot_left_count"], 0)

    def test_far_apart_in_time_not_paired(self):
        stamp = receive_stamp()
        self.store.record(data=b"image", source_id="camera", modality="rgb",
                          reference_frame_id="frame.cam", sequence=1,
                          timestamp=stamp, media_type="application/octet-stream",
                          representation={})
        later = source_receive_stamp("test_robot_read")
        later["received_monotonic_ns"] = stamp["received_monotonic_ns"] + 3_000_000_000
        record_sample(self.store, self.row(stamp=later))
        self.assertEqual(temporal_probe(self.store, max_offset_ms=100)["pair_count"], 0)

    def test_asynchronous_hook_filters_images(self):
        file = self.root / "hook.jsonl"
        publisher = TelemetryJSONL(file, source_id="device.sample", reference_frame_id="frame.device")
        publisher.publish({"shoulder.pos": 42, "elbow.vel": -0.1,
                           "wrist": [[3, 4]], "some_jpeg_frame": b"data", "gripper.torque": float("nan")})
        publisher.close()
        row = json.loads(file.read_text().strip())
        self.assertEqual(set(row["payload"]["measurements"]), {"shoulder.pos", "elbow.vel"})
        result = ingest_jsonl(self.store, file)
        self.assertEqual(result["new_observations"], 1)
        self.assertEqual(self.store.verify()["status"], "PASS")

    def test_synthetic_pairs_fixture_only_on_empty_store(self):
        result = make_synthetic_pair_fixture(self.root / "demo", count=5)
        self.assertIn("SYNTHETIC", result["status"])
        demo = EvidenceStore(self.root / "demo")
        self.assertEqual(demo.verify()["status"], "PASS")
        pairs = temporal_probe(demo, max_offset_ms=10)
        self.assertEqual(pairs["pair_count"], 5)
        self.assertEqual({x["right_minus_left_received_ns"] for x in pairs["pairs"]}, {3_000_000})
        with self.assertRaises(ValueError):
            make_synthetic_pair_fixture(self.root / "demo", count=5)

    def test_empty_hook_fails_loudly(self):
        path = self.root / "emptyhook.jsonl"
        publisher = TelemetryJSONL(path, source_id="device.sample", reference_frame_id="frame.device")
        try:
            with self.assertRaises(ValueError):
                publisher.publish({"camera": [[1,2]], "other": None})
        finally:
            publisher.close()
        self.assertEqual(path.read_text(), "")

    def test_empty_source_no_false_pass(self):
        self.assertEqual(self.store.verify()["status"], "EMPTY")
        with self.assertRaises(ValueError):
            temporal_probe(self.store)


if __name__ == "__main__":
    unittest.main()
