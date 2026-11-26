"""Synthetic bounded intake; no acquisition, private input, network or live store."""
from dataclasses import asdict, replace
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reality_ingress import bounded_intake as intake
from reality_ingress.consumer_ref import verified_ref_from_store
from reality_ingress.evidence import EvidenceStore
from reality_ingress.generic import canonical_json, record_sample
from reality_ingress.interop_numeric import MAX_U64
from reality_ingress.session_binding import SuppliedEvidence, resolve_session

BOOT = "bc7e69f1-4482-4bfc-8bf9-615f56cf31b0"
PAKY = "paky-01/imu_publish.py:IMU-RI-01-candidate"


def scope_fixture(producer=PAKY):
    return intake.SourceScope(producer, "synthetic-robot", "synthetic-imu",
        "synthetic-source", "frame.synthetic.imu", "a"*32, BOOT)


def row_fixture(scope, seq=1, mono=123456789):
    sample = {
        "schema_version": "openrgd.imu-sample.v0.1-candidate",
        "robot_id": scope.robot_id, "sensor_id": scope.sensor_id,
        "source_id": scope.source_id, "sensor_frame_id": scope.frame_id,
        "session_id": scope.session_id, "sequence": seq,
        "host_receive_utc": "2026-11-26T10:00:00Z", "host_monotonic_ns": mono,
        "acceleration_m_s2": [0.0, 0.1, 9.81],
        "angular_velocity_rad_s": [0.01, 0.0, 0.0],
        "orientation_euler_deg": [1.0, 2.0, -150.0],
        "temperature_c": None, "calibration_revision": None,
    }
    wrapper = {
        "console_ingest_sample": sample, "console_delivery_status": "accepted_http_202",
        "source_kind_claim": "physical", "source_verified": False,
        "robot_binding_verified": False, "reference_frame": "imu_sensor_axes_unverified",
        "quality": "unverified", "calibration_revision": None,
        "heading_calibrated": False, "decision_eligible": False,
        "observation_only": True, "history_committed": False, "actuation_enabled": False,
    }
    if scope.producer == intake.GENERALIZED:
        wrapper.update(assembly_policy="strict-no-reuse",
            component_receipt_ages_ns={"acceleration": 10, "angular_velocity": 5, "vendor_euler": 0},
            host_receipt_span_ns=10, synchronized=False)
    return {
        "schema_ref_str": "urn:openrgd:experimental:reality-ingress:source-sample:v0",
        "producer_str": scope.producer,
        "source": {"source_id_str": scope.source_id, "modality_str": "imu",
            "reference_frame_id_str": scope.frame_id, "sample_sequence_uint": seq,
            "session_id_str": scope.session_id},
        "temporal_binding": {
            "received_monotonic_ns": mono, "received_unix_estimate_ns": 1795687200000000000,
            "host_wall_pair_span_ns": 100,
            "clock_domain_ref": {"clock_domain_id_str": "chronos.monotonic.boot:"+scope.boot_id,
                "layer_enum_str": "CHRONOS", "clock_kind_enum_str": "MONOTONIC",
                "epoch_ref_str": "linux-boot:"+scope.boot_id, "timescale_enum_str": "MONOTONIC",
                "boot_id_str": scope.boot_id},
            "receive_timestamp_method": "userspace_after_existing_WIT_serial_read",
            "source_time": None, "source_time_status_str": "UNKNOWN_NOT_EXPOSED_BY_SOURCE",
        },
        "payload": wrapper,
    }


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spool = self.root / "spool"
        self.spool.mkdir(mode=0o700)
        self.scope = scope_fixture()
        self.rows = [row_fixture(self.scope, 1), row_fixture(self.scope, 2, 123456790)]
        self.write(self.rows)

    def write_raw(self, raw, rows, *, with_bytes=False):
        self.path = self.spool / self.scope.filename
        self.path.write_bytes(raw)
        self.path.chmod(0o600)
        self.report = {"state": "COMPLETED", "filename": self.scope.filename,
                       "written": rows, "enqueued": rows, "error_class": None,
                       "history_committed": False, "actuation_enabled": False}
        if with_bytes:
            self.report["written_bytes"] = len(raw)
        return raw

    def write(self, rows, *, with_bytes=False):
        return self.write_raw(b"".join(canonical_json(r)+b"\n" for r in rows),
                              len(rows), with_bytes=with_bytes)

    def preview(self, **kwargs):
        return intake.preview_spool(self.spool, self.scope, self.report, **kwargs)

    def store(self, name="store"):
        return EvidenceStore(self.root / name)

    def apply(self, store, sha=None, **kwargs):
        if sha is None:
            sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        return intake.apply_spool(store, self.spool, self.scope, self.report,
                                  expected_spool_sha256=sha, **kwargs)

    def assert_no_observations(self, store):
        self.assertEqual(list(store.observations.iterdir()), [])
        self.assertEqual(list(store.payloads.rglob("*.bin")), [])

    def test_preview_has_no_store_side_effects(self):
        before = self.path.read_bytes()
        report = self.preview()
        self.assertEqual(report.status, "PREVIEW")
        self.assertEqual(report.input_rows, 2)
        self.assertEqual(report.spool_sha256, hashlib.sha256(before).hexdigest())
        self.assertEqual(report.created, 0)
        self.assertFalse((self.root/"store").exists())
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(report.source_verified)
        self.assertNotIn("payload", asdict(report))

    def test_import_matches_legacy_ids_bytes_and_session(self):
        store, legacy = self.store(), self.store("legacy")
        result = self.apply(store)
        self.assertEqual(result.status, "IMPORTED")
        self.assertEqual(result.created, 2)
        for row in self.rows:
            env, _ = record_sample(legacy, row)
            obs = env["observation_id_str"]
            self.assertEqual(store.get_observation(obs), env)
            self.assertEqual((store.observations/(obs+".json")).read_bytes(),
                             (legacy.observations/(obs+".json")).read_bytes())
            raw = (store.root/env["evidence"]["payload_ref_str"]).read_bytes()
            self.assertEqual(raw, canonical_json(row))
            ref = verified_ref_from_store(store, obs)
            b = resolve_session(SuppliedEvidence(canonical_json(ref), canonical_json(env), raw))
            self.assertEqual(b.status, "CONTENT_MATCHED")
            self.assertEqual(b.binding.key.session_id, self.scope.session_id)
            self.assertFalse(b.binding.source_verified)
        self.assertEqual(store.verify()["status"], "PASS")

    def test_explicit_reimport_idempotent(self):
        store = self.store()
        self.assertEqual(self.apply(store).created, 2)
        result = self.apply(store)
        self.assertEqual((result.status, result.created, result.already_present),
                         ("IMPORTED", 0, 2))

    def test_duplicate_exact_rows_collapse(self):
        self.write([self.rows[0], self.rows[0], self.rows[1]])
        report = self.preview()
        self.assertEqual((report.input_rows, report.unique_rows, report.duplicate_rows), (3, 2, 1))
        self.assertEqual(self.apply(self.store()).created, 2)

    def test_same_sequence_different_payload_rejected_before_writes(self):
        conflict = deepcopy(self.rows[0])
        conflict["payload"]["console_ingest_sample"]["temperature_c"] = 21.0
        self.write([self.rows[0], conflict])
        store = self.store()
        self.assertEqual(self.apply(store).reason, "SESSION_SEQUENCE_CONFLICT")
        self.assert_no_observations(store)

    def test_invalid_last_record_preflight_writes_nothing(self):
        self.write_raw(canonical_json(self.rows[0])+b"\n"+b"{bad}\n", 2)
        store = self.store()
        self.assertEqual(self.apply(store).status, "REJECTED")
        self.assert_no_observations(store)

    def test_preview_hash_mismatch_after_change(self):
        before = self.preview().spool_sha256
        row = deepcopy(self.rows[1])
        row["payload"]["console_ingest_sample"]["temperature_c"] = 23
        self.write([self.rows[0], row])
        store = self.store()
        self.assertEqual(self.apply(store, before).reason, "PREVIEW_HASH_MISMATCH")
        self.assert_no_observations(store)

    def test_completion_report_required(self):
        for state in ("FAILED", "WRITER_TIMEOUT", "EMPTY", None):
            with self.subTest(state=state):
                self.report["state"] = state
                self.assertEqual(self.preview().status, "REJECTED")

    def test_completion_count_and_bytes_match(self):
        self.report["written"] = self.report["enqueued"] = 1
        self.assertEqual(self.preview().reason, "COMPLETION_COUNT_MISMATCH")
        self.write(self.rows, with_bytes=True)
        self.report["written_bytes"] += 1
        self.assertEqual(self.preview().reason, "COMPLETION_BYTES_MISMATCH")

    def test_part_file_blocks_even_if_final_exists(self):
        (self.spool/(self.scope.filename+".part")).write_bytes(b"partial")
        self.assertEqual(self.preview().reason, "PART_FILE_PRESENT")

    def test_truncated_and_blank_records(self):
        self.write_raw(canonical_json(self.rows[0]), 1)
        self.assertEqual(self.preview().reason, "UNTERMINATED_OR_EMPTY_SPOOL")
        self.write_raw(canonical_json(self.rows[0])+b"\n\n", 2)
        self.assertEqual(self.preview().reason, "LINE_BYTE_OR_FORMAT_LIMIT")

    def test_file_and_directory_privacy(self):
        self.path.chmod(0o644)
        self.assertEqual(self.preview().reason, "PRIVATE_REGULAR_FILE_REQUIRED")
        self.path.chmod(0o600)
        self.spool.chmod(0o755)
        self.assertEqual(self.preview().reason, "PRIVATE_DIRECTORY_REQUIRED")

    def test_symlink_hardlink_and_fifo_rejected(self):
        raw = self.path.read_bytes()
        other = self.spool/"other"
        other.write_bytes(raw); other.chmod(0o600)
        self.path.unlink(); self.path.symlink_to(other)
        self.assertEqual(self.preview().status, "REJECTED")
        self.path.unlink(); os.link(other, self.path)
        self.assertEqual(self.preview().reason, "PRIVATE_REGULAR_FILE_REQUIRED")
        self.path.unlink(); os.mkfifo(self.path, 0o600)
        self.assertEqual(self.preview().reason, "PRIVATE_REGULAR_FILE_REQUIRED")

    def test_spool_and_line_and_write_budgets_independent(self):
        for limits in (intake.IntakeLimits(max_spool_bytes=32),
                       intake.IntakeLimits(max_line_bytes=32),
                       intake.IntakeLimits(max_planned_write_bytes=32),
                       intake.IntakeLimits(max_rows=1)):
            with self.subTest(limits=limits):
                self.assertEqual(self.preview(limits=limits).status, "REJECTED")

    def test_limit_overrides_cannot_raise_ceiling_or_be_bool(self):
        for kwargs in ({"max_rows":61}, {"max_line_bytes":4097},
                       {"max_spool_bytes":intake.MAX_SPOOL_BYTES+1},
                       {"max_planned_write_bytes":intake.MAX_PLANNED_WRITE_BYTES+1},
                       {"max_rows":True}, {"max_rows":0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(intake.IntakeError):
                intake.IntakeLimits(**kwargs)

    def test_u64_large_valid_even_with_small_spool_budget(self):
        self.write([row_fixture(self.scope, MAX_U64, MAX_U64)])
        self.assertEqual(self.preview().status, "PREVIEW")
        self.assertEqual(self.apply(self.store()).created, 1)

    def test_numeric_overflow_all_source_counters(self):
        for path in (("source","sample_sequence_uint"),
                     ("temporal_binding","received_monotonic_ns"),
                     ("temporal_binding","received_unix_estimate_ns"),
                     ("temporal_binding","host_wall_pair_span_ns")):
            row = deepcopy(self.rows[0])
            row[path[0]][path[1]] = MAX_U64+1
            self.write([row])
            with self.subTest(path=path):
                self.assertEqual(self.preview().reason, "OUTSIDE_NATIVE_U64_DOMAIN")

    def test_float_boolean_string_counter_rejected(self):
        for invalid in (1.0, True, "1", -1):
            row = deepcopy(self.rows[0]); row["source"]["sample_sequence_uint"] = invalid
            self.write([row])
            with self.subTest(invalid=invalid):
                self.assertEqual(self.preview().status, "REJECTED")

    def test_source_session_boot_identity_and_duplicate_sample_mismatch(self):
        for target, key, value in (
            ("source", "session_id_str", "b"*32),
            ("source", "source_id_str", "wrong"),
            ("source", "reference_frame_id_str", "wrong"),
            ("source", "modality_str", "rgb"),
            ("sample", "sensor_id", "wrong"),
            ("sample", "robot_id", "wrong"),
            ("sample", "session_id", "b"*32),
            ("sample", "host_monotonic_ns", 2),
        ):
            row = deepcopy(self.rows[0])
            obj = row["payload"]["console_ingest_sample"] if target == "sample" else row[target]
            obj[key] = value
            self.write([row])
            with self.subTest(target=target,key=key):
                self.assertEqual(self.preview().status, "REJECTED")
        row = deepcopy(self.rows[0])
        row["temporal_binding"]["clock_domain_ref"]["boot_id_str"] = "wrong"
        self.write([row])
        self.assertEqual(self.preview().status, "REJECTED")

    def test_out_of_order_and_receipt_regression(self):
        self.write(self.rows[::-1])
        self.assertEqual(self.preview().reason, "SOURCE_ORDER_CONFLICT")
        self.write([self.rows[0], row_fixture(self.scope,2,1)])
        self.assertEqual(self.preview().reason, "SOURCE_ORDER_CONFLICT")

    def test_fake_authority_and_unapproved_representation(self):
        for key in ("source_verified", "robot_binding_verified", "history_committed",
                    "actuation_enabled", "heading_calibrated", "decision_eligible"):
            row = deepcopy(self.rows[0]); row["payload"][key] = True
            self.write([row])
            with self.subTest(key=key):
                self.assertEqual(self.preview().status, "REJECTED")
        row = deepcopy(self.rows[0])
        row["payload"] = {"representation_profile":"cog-ri-02.console-copy.v0.1-candidate"}
        self.write([row])
        self.assertEqual(self.preview().status, "REJECTED")

    def test_duplicate_json_keys_nonfinite_and_invalid_utf8(self):
        for raw in (b'{"x":1,"x":2}\n', b'{"x":NaN}\n', b'{"x":1e999}\n', b'\xff\n'):
            self.write_raw(raw, 1)
            with self.subTest(raw=raw):
                self.assertEqual(self.preview().status, "REJECTED")

    def test_generalized_profile_optional_metadata_preserved(self):
        self.scope = scope_fixture(intake.GENERALIZED)
        row = row_fixture(self.scope)
        self.write([row], with_bytes=True)
        store = self.store()
        self.assertEqual(self.apply(store).status, "IMPORTED")
        env, _ = record_sample(self.store("legacy"), row)
        self.assertEqual((store.root/env["evidence"]["payload_ref_str"]).read_bytes(), canonical_json(row))

    def test_generalized_profile_rejects_fake_sync_and_overflow(self):
        self.scope = scope_fixture(intake.GENERALIZED)
        for field, value in (("synchronized",True), ("host_receipt_span_ns",MAX_U64+1)):
            row = row_fixture(self.scope); row["payload"][field]=value
            self.write([row], with_bytes=True)
            with self.subTest(field=field):
                self.assertEqual(self.preview().status, "REJECTED")

    def test_corrupt_existing_payload_fails_before_any_new_record(self):
        store = self.store()
        env, _ = record_sample(store, self.rows[1])
        (store.root/env["evidence"]["payload_ref_str"]).write_bytes(b"wrong")
        result = self.apply(store)
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.created, 0)
        self.assertEqual(len(list(store.observations.glob("*.json"))), 1)

    def test_existing_observation_missing_payload_not_repaired(self):
        store = self.store()
        env, _ = record_sample(store, self.rows[1])
        (store.root/env["evidence"]["payload_ref_str"]).unlink()
        self.assertEqual(self.apply(store).reason,"EXISTING_OBSERVATION_MISSING_PAYLOAD")
        self.assertEqual(len(list(store.observations.glob("*.json"))), 1)

    def test_existing_symlink_rejected_without_touching_target(self):
        store = self.store()
        digest = hashlib.sha256(canonical_json(self.rows[0])).hexdigest()
        sub = store.payloads/digest[:2]; sub.mkdir(mode=0o700)
        outside = self.root/"outside"; outside.write_bytes(b"do not touch")
        (sub/(digest+".bin")).symlink_to(outside)
        self.assertEqual(self.apply(store).status, "REJECTED")
        self.assertEqual(outside.read_bytes(), b"do not touch")
        self.assertEqual(len(list(store.observations.glob("*.json"))),0)

    def test_intake_lock_is_nonblocking(self):
        store = self.store()
        fd = os.open(store.root, os.O_RDONLY|os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertEqual(self.apply(store).reason, "INTAKE_BUSY")
            self.assert_no_observations(store)
        finally:
            os.close(fd)

    def test_interrupted_prefix_reimport_recovers_without_rollback_claim(self):
        store = self.store()
        real = record_sample
        def broken(s, row):
            if row["source"]["sample_sequence_uint"] == 2:
                s.put_payload(canonical_json(row))  # orphan before manifest
                raise OSError("injected fault")
            return real(s, row)
        with patch.object(intake, "record_sample", side_effect=broken):
            result = self.apply(store)
        self.assertEqual((result.status,result.created,result.completed,result.failed_line),
                         ("PARTIAL_OR_UNCERTAIN",1,1,2))
        self.assertEqual(len(list(store.payloads.rglob("*.bin"))),2)
        retry = self.apply(store, result.spool_sha256)
        self.assertEqual((retry.status,retry.created,retry.already_present),("IMPORTED",1,1))
        self.assertEqual(store.verify()["status"],"PASS")

    def test_error_after_manifest_creation_is_uncertain_not_rolled_back(self):
        store = self.store()
        def uncertain(s,row):
            record_sample(s,row)
            raise OSError("injected after commit")
        with patch.object(intake,"record_sample",side_effect=uncertain):
            result = self.apply(store)
        self.assertEqual((result.status,result.completed,result.failed_line),
                         ("PARTIAL_OR_UNCERTAIN",0,1))
        self.assertEqual(len(list(store.observations.glob("*.json"))),1)
        retry = self.apply(store, result.spool_sha256)
        self.assertEqual((retry.created,retry.already_present),(1,1))

    def test_store_root_must_be_private_and_no_auto_delete(self):
        store=self.store()
        store.root.chmod(0o755)
        self.assertEqual(self.apply(store).status,"REJECTED")
        self.assertTrue(self.path.is_file())
        self.assert_no_observations(store)


if __name__ == "__main__":
    unittest.main()
