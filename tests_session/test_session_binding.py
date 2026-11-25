"""Synthetic RI-A02 tests using the original v0.4 store and RI #4 projection."""
from dataclasses import asdict, replace
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from reality_ingress.consumer_ref import verified_ref_from_store, unverified_ref_from_envelope
from reality_ingress.evidence import EvidenceStore
from reality_ingress.generic import canonical_json, record_sample, SAMPLE_SCHEMA
from reality_ingress.session_binding import (
    SuppliedEvidence, SessionKey, resolve_session, resolve_unique, BindingError,
    MAX_REF_BYTES, MAX_SAMPLE_BYTES, MAX_CANDIDATES, MAX_BATCH_BYTES, COG_COPY_PROFILE,
)

BOOT = "bc7e69f1-4482-4bfc-8bf9-615f56cf31b0"


def row_fixture():
    return {
        "schema_ref_str": SAMPLE_SCHEMA,
        "producer_str": "synthetic-fixture-not-physical",
        "source": {
            "source_id_str": "source.synthetic.imu",
            "reference_frame_id_str": "frame.synthetic.imu",
            "modality_str": "imu",
            "sample_sequence_uint": 7,
            "session_id_str": "a" * 32,
        },
        "temporal_binding": {
            "received_monotonic_ns": 123456789,
            "received_unix_estimate_ns": 1795600800000000000,
            "host_wall_pair_span_ns": 100,
            "clock_domain_ref": {
                "clock_domain_id_str": "chronos.monotonic.boot:" + BOOT,
                "clock_kind_enum_str": "MONOTONIC", "boot_id_str": BOOT,
            },
            "source_time": None,
            "source_time_status_str": "UNKNOWN_NOT_EXPOSED_BY_SOURCE",
        },
        "payload": {"measurements": {"x": 0.1}},
    }


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = EvidenceStore(Path(self.tmp.name) / "store")
        self.row = row_fixture()
        self.item = self.record(self.row)
        self.key = resolve_session(self.item).binding.key

    def record(self, row):
        env, _ = record_sample(self.store, row)
        ref = verified_ref_from_store(self.store, env["observation_id_str"])
        return SuppliedEvidence(canonical_json(ref), canonical_json(env), canonical_json(row))

    def rewrite(self, item, field, update):
        obj = json.loads(getattr(item, field))
        update(obj)
        return replace(item, **{field: canonical_json(obj)})

    def test_exact_generic_resolution_no_authority(self):
        result = resolve_session(self.item, expected=self.key)
        self.assertEqual(result.status, "CONTENT_MATCHED")
        b = result.binding
        self.assertEqual(b.key.session_id, "a" * 32)
        self.assertEqual(b.key.boot_id, BOOT)
        self.assertEqual(b.payload_sha256_hex, hashlib.sha256(self.item.payload).hexdigest())
        self.assertEqual(b.observation_id, json.loads(self.item.reference)["observation_id"])
        for flag in ("source_verified", "robot_binding_verified", "history_committed", "actuation_enabled"):
            self.assertFalse(getattr(b, flag))
        self.assertIsNone(b.publisher_host_id)
        self.assertEqual(b.clock_relation, "NOT_ESTABLISHED")
        self.assertEqual(b.freshness, "UNKNOWN")
        self.assertFalse(result.access_verified)
        self.assertFalse(result.reference_issuance_verified)
        self.assertFalse(result.store_availability_verified)
        self.assertNotIn("payload", asdict(result))

    def test_unverified_reference_does_not_upgrade_issuance(self):
        item = self.rewrite(self.item, "reference",
                            lambda d: d.update(integrity_status="not_verified"))
        result = resolve_session(item)
        self.assertEqual(result.status, "CONTENT_MATCHED")
        self.assertFalse(result.reference_issuance_verified)

    def test_reference_schema_unchanged_no_session(self):
        ref = json.loads(self.item.reference)
        self.assertNotIn("session_id", ref)
        self.assertEqual(ref["schema_version"], "ri.consumer-observation-ref.v0.1-candidate")
        self.assertEqual(resolve_session(self.item).binding.key, self.key)

    def test_missing_input(self):
        self.assertEqual(resolve_session(None).reason, "INPUT_NOT_SUPPLIED")

    def test_session_mismatch_same_sequence(self):
        other = replace(self.key, session_id="b" * 32)
        self.assertEqual(resolve_session(self.item, expected=other).status, "MISMATCH")

    def test_boot_or_clock_mismatch(self):
        for changed in (replace(self.key, boot_id="other-boot"),
                        replace(self.key, clock_domain_id="other-clock")):
            with self.subTest(changed=changed):
                self.assertEqual(resolve_session(self.item, expected=changed).status, "MISMATCH")

    def test_new_session_and_reboot_remain_separate(self):
        row = deepcopy(self.row)
        row["source"]["session_id_str"] = "b" * 32
        row["temporal_binding"]["clock_domain_ref"]["boot_id_str"] = "new-boot"
        row["temporal_binding"]["clock_domain_ref"]["clock_domain_id_str"] = "chronos.monotonic.boot:new-boot"
        other = self.record(row)
        self.assertEqual(resolve_unique((self.item, other), self.key).reason, "UNIQUE_IN_SUPPLIED_SET")
        self.assertEqual(resolve_session(other, expected=self.key).status, "MISMATCH")

    def test_no_session_no_inference(self):
        row = deepcopy(self.row)
        row["source"].pop("session_id_str")
        row["payload"]["session_id"] = "a" * 32
        self.assertEqual(resolve_session(self.record(row)).reason, "SOURCE_SESSION_NOT_RECORDED")

    def test_bad_session_rejected(self):
        for bad in ("unknown", "0" * 32, "", 1, True):
            row = deepcopy(self.row)
            row["source"]["session_id_str"] = bad
            with self.subTest(bad=bad):
                self.assertEqual(resolve_session(self.record(row)).reason, "INVALID_SOURCE_SESSION")

    def test_unknown_clock_label_not_fabricated(self):
        row = deepcopy(self.row)
        row["temporal_binding"]["clock_domain_ref"]["clock_domain_id_str"] = "unknown"
        self.assertEqual(resolve_session(self.record(row)).reason, "CLOCK_LABEL_NOT_RESOLVED")

    def test_payload_corruption(self):
        result = resolve_session(replace(self.item, payload=self.item.payload + b"x"))
        self.assertEqual(result.reason, "PAYLOAD_HASH_OR_SIZE_MISMATCH")

    def test_ref_mismatch_and_authority_rejected(self):
        for field, value in (("source_verified", True), ("history_committed", True),
                             ("actuation_enabled", True), ("robot_binding_verified", True),
                             ("sample_sequence", True), ("source_id", "other"),
                             ("observation_id", "obs_" + "0" * 32),
                             ("session_id", "invented")):
            item = self.rewrite(self.item, "reference", lambda d: d.update({field: value}))
            with self.subTest(field=field):
                self.assertEqual(resolve_session(item).status, "REJECTED")

    def test_reference_time_forgery(self):
        item = self.rewrite(self.item, "reference",
                            lambda d: d["time"].update(chronograf_anchor_ref="fake"))
        self.assertEqual(resolve_session(item).status, "REJECTED")

    def test_generic_envelope_metadata_tamper_even_if_ref_agrees(self):
        env = json.loads(self.item.envelope)
        env["source"]["session_id_str"] = "b" * 32
        ref = unverified_ref_from_envelope(env)
        item = replace(self.item, reference=canonical_json(ref), envelope=canonical_json(env))
        self.assertEqual(resolve_session(item).reason, "GENERIC_ENVELOPE_COMMITMENT_MISMATCH")

    def test_generic_payload_ref_path_not_dereferenced(self):
        item = self.rewrite(self.item, "envelope",
                            lambda d: d["evidence"].update(payload_ref_str="../../outside"))
        self.assertEqual(resolve_session(item).reason, "GENERIC_ENVELOPE_COMMITMENT_MISMATCH")

    def test_camera_session_refused_even_with_payload_hash(self):
        env = self.store.record(data=b"synthetic-frame", source_id="camera",
            modality="rgb", reference_frame_id="frame.camera", sequence=7,
            timestamp=self.row["temporal_binding"], media_type="image/jpeg",
            representation={"kind_str": "synthetic"})
        ref = verified_ref_from_store(self.store, env["observation_id_str"])
        item = SuppliedEvidence(canonical_json(ref), canonical_json(env), b"synthetic-frame")
        result = resolve_session(item)
        self.assertEqual(result.reason, "LEGACY_CAMERA_SESSION_NOT_BOUND")
        self.assertIsNone(result.binding)
        env["source"]["session_id_str"] = "forged"
        tampered = SuppliedEvidence(canonical_json(unverified_ref_from_envelope(env)),
                                   canonical_json(env), b"synthetic-frame")
        self.assertEqual(resolve_session(tampered).reason, "LEGACY_CAMERA_SESSION_NOT_BOUND")

    def test_proposed_cog_copy_profile_not_adopted(self):
        row = deepcopy(self.row)
        row["payload"] = {"representation_profile": COG_COPY_PROFILE,
                          "console_imu_record": {"session_id": "a" * 32}}
        self.assertEqual(resolve_session(self.record(row)).reason, "CONSOLE_COPY_PROFILE_REVIEW_PENDING")

    def imu_row(self):
        row = deepcopy(self.row)
        row["payload"] = {
            "console_ingest_sample": {
                "schema_version": "openrgd.imu-sample.v0.1-candidate",
                "source_id": row["source"]["source_id_str"],
                "sensor_frame_id": row["source"]["reference_frame_id_str"],
                "session_id": row["source"]["session_id_str"],
                "sequence": row["source"]["sample_sequence_uint"],
                "host_monotonic_ns": row["temporal_binding"]["received_monotonic_ns"],
            },
            "source_verified": False, "robot_binding_verified": False,
            "history_committed": False, "actuation_enabled": False,
            "heading_calibrated": False, "decision_eligible": False,
            "observation_only": True, "calibration_revision": None,
        }
        return row

    def test_imu_original_fields_consistent(self):
        self.assertEqual(resolve_session(self.record(self.imu_row())).status, "CONTENT_MATCHED")

    def test_imu_original_fields_mismatch(self):
        for field, value in (("session_id", "b" * 32), ("sequence", 8),
                             ("host_monotonic_ns", 123456790),
                             ("sensor_frame_id", "wrong-frame")):
            row = self.imu_row()
            row["payload"]["console_ingest_sample"][field] = value
            with self.subTest(field=field):
                self.assertEqual(resolve_session(self.record(row)).reason, "ORIGINAL_SOURCE_SAMPLE_MISMATCH")

    def test_imu_authority_false_required(self):
        row = self.imu_row()
        row["payload"]["decision_eligible"] = True
        self.assertEqual(resolve_session(self.record(row)).reason, "UNSUPPORTED_IMU_AUTHORITY")

    def test_duplicate_json_rejected(self):
        raw = b'{"a":1,"a":2}'
        self.assertEqual(resolve_session(replace(self.item, reference=raw)).reason, "DUPLICATE_JSON_KEY")

    def test_nonfinite_and_deep_json_rejected(self):
        for raw in (b'{"a":NaN}', b'{"a":1e999}', b'{"a":' + b'[' * 40 + b'0' + b']' * 40 + b'}'):
            with self.subTest(raw=raw[:40]):
                self.assertEqual(resolve_session(replace(self.item, reference=raw)).status, "REJECTED")

    def test_input_and_payload_limits(self):
        self.assertEqual(resolve_session(replace(self.item, reference=b"x" * (MAX_REF_BYTES + 1))).reason,
                         "INPUT_LIMIT")
        self.assertEqual(resolve_session(replace(self.item, payload=b"x" * (MAX_SAMPLE_BYTES + 1))).reason,
                         "PAYLOAD_LIMIT")

    def test_batch_duplicate_idempotent(self):
        result = resolve_unique((self.item, self.item), self.key)
        self.assertEqual(result.reason, "UNIQUE_IN_SUPPLIED_SET")
        self.assertEqual(result.binding.key, self.key)

    def test_batch_same_key_different_digest_ambiguous(self):
        row = deepcopy(self.row)
        row["payload"]["measurements"]["x"] = 0.2
        other = self.record(row)
        result = resolve_unique((self.item, other), self.key)
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIsNone(result.binding)

    def test_batch_no_false_unique_on_invalid_candidate(self):
        corrupted = replace(self.item, payload=b"invalid")
        self.assertEqual(resolve_unique((self.item, corrupted), self.key).reason,
                         "CANDIDATE_SET_NOT_FULLY_RESOLVED")

    def test_batch_no_match_and_limits(self):
        self.assertEqual(resolve_unique((), self.key).reason, "NO_MATCH_IN_SUPPLIED_SET")
        self.assertEqual(resolve_unique((self.item,) * (MAX_CANDIDATES + 1), self.key).reason,
                         "BATCH_LIMIT_OR_TYPE")
        large = replace(self.item, payload=b"x" * (MAX_BATCH_BYTES + 1))
        self.assertEqual(resolve_unique((large,), self.key).reason, "BATCH_BYTE_LIMIT")

    def test_invalid_selector_rejected(self):
        with self.assertRaises(BindingError):
            replace(self.key, sequence=True)

    def test_inputs_and_store_unchanged(self):
        files = {p.relative_to(self.store.root): p.read_bytes()
                 for p in self.store.root.rglob("*") if p.is_file()}
        before = self.item
        resolve_session(self.item)
        resolve_unique((self.item,), self.key)
        self.assertEqual(before, self.item)
        self.assertEqual(files, {p.relative_to(self.store.root): p.read_bytes()
                                for p in self.store.root.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
