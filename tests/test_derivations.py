import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from reality_ingress.derivations import DerivationStore
from reality_ingress.evidence import EvidenceStore, IntegrityError
from reality_ingress.perception import derive
from reality_ingress.timebase import receive_stamp


class PerceptionDerivationTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.store = EvidenceStore(self.work.name)
        self.derivations = DerivationStore(self.store)

    def record(self, sequence=1):
        return self.store.record(
            data=b"synthetic-test-jpeg-bytes", source_id="camera.001",
            modality="rgb", reference_frame_id="cam.001",
            sequence=sequence, timestamp=receive_stamp(), media_type="image/jpeg",
            representation={"kind_str": "synthetic_test_fixture"},
        )

    def fake_detection(self):
        return [{"class_id_uint": 0, "class_label_str": "person",
                 "confidence_float": 0.95,
                 "bbox_xyxy_normalized_arr": [0.1, 0.2, 0.8, 0.9]}]

    def processor(self):
        return {"processor_name_str": "fixture-detector",
                "model": {"weights_sha256_hex_str": "b" * 64},
                "parameters": {"confidence_threshold_float": 0.35}}

    def test_derivation_references_original_without_rewriting(self):
        original = self.record()
        observation_file = self.store.observations / (original["observation_id_str"] + ".json")
        snapshot = observation_file.read_bytes()
        rec = self.derivations.create(observation_id=original["observation_id_str"],
                                      processor=self.processor(), detections=self.fake_detection())
        self.assertEqual(observation_file.read_bytes(), snapshot)
        self.assertEqual(rec["derived_from"]["observation_id_str"], original["observation_id_str"])
        self.assertEqual(rec["derived_from"]["observation_envelope_sha256_hex_str"], hashlib.sha256(snapshot).hexdigest())
        self.assertEqual(self.store.verify()["status"], "PASS")
        self.assertEqual(self.store.verify()["derivation_count"], 1)
        self.assertEqual(rec["temporal_binding"]["chronograf_alignment_status_str"], "NOT_RESOLVED_BY_CHRONOGRAF")

    def test_multiple_derivations_over_one_observation(self):
        o = self.record()
        self.derivations.create(observation_id=o["observation_id_str"],
                                processor=self.processor(), detections=self.fake_detection())
        self.derivations.create(observation_id=o["observation_id_str"],
                                processor={"processor_name_str": "other-model"}, detections=[])
        result = self.store.verify()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["observation_count"], 1)
        self.assertEqual(result["derivation_count"], 2)
        self.assertEqual(result["referenced_observation_count"], 1)

    def test_derivation_tampering_detected(self):
        o = self.record()
        d = self.derivations.create(observation_id=o["observation_id_str"],
                                    processor=self.processor(), detections=self.fake_detection())
        p = self.derivations._path(d["derivation_id_str"])
        p.write_bytes(p.read_bytes().replace(b'"person"', b'"bottle"'))
        v = self.store.verify()
        self.assertEqual(v["status"], "FAIL")
        self.assertIn("Derivation content hash mismatch", str(v["errors"]))

    def test_source_envelope_tampering_after_derivation_detected(self):
        o = self.record()
        self.derivations.create(observation_id=o["observation_id_str"],
                                processor=self.processor(), detections=self.fake_detection())
        p = self.store.observations / (o["observation_id_str"] + ".json")
        p.write_bytes(p.read_bytes() + b" ")
        self.assertEqual(self.store.verify()["status"], "FAIL")
        self.assertIn("Source observation envelope modified", str(self.store.verify()["errors"]))

    def test_source_payload_tampering_detected(self):
        o = self.record()
        self.derivations.create(observation_id=o["observation_id_str"],
                                processor=self.processor(), detections=self.fake_detection())
        p = self.store._payload_path(o["evidence"]["payload_sha256_hex_str"])
        p.write_bytes(b"TAMPERED")
        self.assertEqual(self.store.verify()["status"], "FAIL")

    def test_dont_accept_self_as_detector_class(self):
        o = self.record()
        wrong = self.fake_detection()
        wrong[0]["class_label_str"] = "SELF"
        with self.assertRaisesRegex(ValueError, "SELF"):
            self.derivations.create(observation_id=o["observation_id_str"],
                                    processor=self.processor(), detections=wrong)
        self.assertEqual(self.store.verify()["derivation_count"], 0)

    def test_derive_offline_and_idempotent(self):
        self.record()
        self.record(2)
        fake = lambda _: self.fake_detection()
        r1 = derive(out=self.work.name, limit=10, injected_predictor=fake,
                    injected_processor=self.processor())
        r2 = derive(out=self.work.name, limit=10, injected_predictor=fake,
                    injected_processor=self.processor())
        self.assertEqual(r1["processed"], 2)
        self.assertEqual(r2["processed"], 0)
        self.assertEqual(r2["already_derived"], 2)
        self.assertEqual(self.store.verify()["status"], "PASS")

    def test_empty_store_not_pass(self):
        self.assertEqual(self.store.verify()["status"], "EMPTY")
        with self.assertRaisesRegex(IntegrityError, "must pass verification"):
            derive(out=self.work.name, injected_predictor=lambda _: [],
                   injected_processor=self.processor())

    def test_no_chronon_and_multiagent_reference(self):
        o = self.record()
        r = self.derivations.create(observation_id=o["observation_id_str"],
                                    processor=self.processor(), detections=self.fake_detection())
        serialized = json.dumps(r).lower()
        self.assertNotIn('"agent_id_str"', serialized)
        self.assertNotIn('"self"', serialized)
        self.assertNotIn('chronon_id', serialized)
        self.assertEqual(self.store.verify()["unique_payload_count"], 1)


if __name__ == "__main__":
    unittest.main()
