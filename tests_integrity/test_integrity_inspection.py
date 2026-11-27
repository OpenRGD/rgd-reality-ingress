"""Synthetic offline RI-A05 tests. No live data, no hardware, no access grant."""
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reality_ingress import integrity_inspection as integrity
from reality_ingress.evidence import EvidenceStore
from reality_ingress.consumer_ref import verified_ref_from_store
from reality_ingress.generic import canonical_json, record_sample
from reality_ingress.timebase import receive_stamp

def sample():
    return {
        "schema_ref_str": "urn:openrgd:experimental:reality-ingress:source-sample:v0",
        "producer_str": "synthetic-a05-fixture",
        "source": {"source_id_str":"synthetic-imu","modality_str":"imu",
            "reference_frame_id_str":"frame.synthetic.imu","sample_sequence_uint":1,
            "session_id_str":"a"*32},
        "temporal_binding": {
            "received_monotonic_ns":123456789, "received_unix_estimate_ns":1795788000000000000,
            "host_wall_pair_span_ns":10,"source_time":None,
            "source_time_status_str":"UNKNOWN_NOT_EXPOSED_BY_SOURCE",
            "clock_domain_ref":{"clock_domain_id_str":"chronos.monotonic.boot:synthetic-boot",
                "boot_id_str":"synthetic-boot","clock_kind_enum_str":"MONOTONIC"}},
        "payload":{"measurements":{"temperature":21.0}},
    }


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"store"
        self.store=EvidenceStore(self.root)
        self.env,_=record_sample(self.store,sample())
        self.obs=self.env["observation_id_str"]
        self.manifest=self.store.observations/(self.obs+".json")
        self.payload=self.root/self.env["evidence"]["payload_ref_str"]

    def check(self,obs=None,**kw):
        return integrity.verify_selected(self.root,self.obs if obs is None else obs,**kw)

    def camera(self):
        env=self.store.record(data=b"synthetic camera bytes",source_id="synthetic-camera",
            modality="rgb",reference_frame_id="frame.synthetic.camera",sequence=1,
            timestamp=receive_stamp(),media_type="image/jpeg",
            representation={"kind_str":"synthetic"})
        obs=env["observation_id_str"]
        return env,obs,self.store.observations/(obs+".json")

    def test_generic_full_content_and_no_authority(self):
        result=self.check()
        self.assertEqual(result.status,"CHECKED",result)
        self.assertEqual(result.envelope_integrity,"GENERIC_CONTENT_MATCHED")
        self.assertEqual(result.payload_integrity,"HASH_AND_SIZE_MATCHED")
        self.assertEqual(result.checkpoint_status,"NEW_BASELINE_ONLY")
        cp=result.checkpoint
        self.assertEqual(cp.observation_id,self.obs)
        self.assertEqual(cp.envelope_sha256,hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        self.assertEqual(cp.payload_sha256,hashlib.sha256(self.payload.read_bytes()).hexdigest())
        self.assertEqual(cp.sha256,hashlib.sha256(cp.canonical_bytes()).hexdigest())
        self.assertFalse(result.source_verified)
        self.assertFalse(result.robot_binding_verified)
        self.assertFalse(result.historical_capture_verified)
        self.assertFalse(result.access_verified)
        self.assertFalse(result.history_committed)
        self.assertFalse(result.actuation_enabled)
        self.assertNotIn(self.obs,repr(result))
        self.assertNotIn(str(self.root),repr(result))

    def test_checkpoint_matches_only_independent_expected_digest(self):
        first=self.check()
        later=self.check(expected_checkpoint_sha256=first.checkpoint.sha256)
        self.assertEqual(later.status,"CHECKED")
        self.assertEqual(later.checkpoint_status,"MATCHED_SUPPLIED_CHECKPOINT")
        self.assertFalse(later.historical_capture_verified)
        wrong=self.check(expected_checkpoint_sha256="f"*64)
        self.assertEqual((wrong.status,wrong.reason),("REJECTED","CHECKPOINT_MISMATCH"))
        self.assertIsNone(wrong.checkpoint)

    def test_camera_metadata_gap_and_checkpoint_detection(self):
        env,obs,path=self.camera()
        first=self.check(obs)
        self.assertEqual(first.envelope_integrity,"LEGACY_ENVELOPE_UNBOUND")
        self.assertEqual(first.checkpoint_status,"NEW_BASELINE_ONLY")
        self.assertEqual(self.check(obs,expected_checkpoint_sha256=first.checkpoint.sha256).status,"CHECKED")
        env["source"]["source_id_str"]="altered-camera-label"
        path.write_bytes(canonical_json(env))
        # Characterize the legacy API, do NOT change its behavior.
        self.assertEqual(verified_ref_from_store(self.store,obs)["source_id"],"altered-camera-label")
        second=self.check(obs)
        self.assertEqual(second.status,"CHECKED")
        self.assertEqual(second.envelope_integrity,"LEGACY_ENVELOPE_UNBOUND")
        self.assertEqual(second.checkpoint_status,"NEW_BASELINE_ONLY")
        self.assertFalse(second.historical_capture_verified)
        self.assertNotEqual(first.checkpoint.sha256,second.checkpoint.sha256)
        mismatch=self.check(obs,expected_checkpoint_sha256=first.checkpoint.sha256)
        self.assertEqual(mismatch.reason,"CHECKPOINT_MISMATCH")
        self.assertIsNone(mismatch.checkpoint)

    def test_camera_exact_envelope_bytes_not_only_projection(self):
        env,obs,path=self.camera()
        cp=self.check(obs).checkpoint.sha256
        # Field not projected into compact ref.
        env["provenance"]["derivation_str"]="different claim"
        path.write_bytes(canonical_json(env))
        self.assertEqual(self.check(obs,expected_checkpoint_sha256=cp).reason,"CHECKPOINT_MISMATCH")

    def test_generic_envelope_metadata_tamper_rejected(self):
        env=deepcopy(self.env)
        env["source"]["session_id_str"]="b"*32
        self.manifest.write_bytes(canonical_json(env))
        self.assertEqual(self.check().reason,"GENERIC_ENVELOPE_COMMITMENT_MISMATCH")

    def test_generic_json_formatting_changes_exact_checkpoint(self):
        before=self.check().checkpoint.sha256
        self.manifest.write_bytes(canonical_json(self.env))
        self.assertEqual(self.check().envelope_integrity,"GENERIC_CONTENT_MATCHED")
        self.assertEqual(self.check(expected_checkpoint_sha256=before).reason,"CHECKPOINT_MISMATCH")

    def test_corrupt_payload_rejected(self):
        self.payload.write_bytes(b"x"*self.payload.stat().st_size)
        self.assertEqual(self.check().reason,"PAYLOAD_HASH_OR_SIZE_MISMATCH")

    def test_missing_selected_files(self):
        self.payload.unlink()
        self.assertEqual(self.check().status,"UNAVAILABLE")
        self.manifest.unlink()
        self.assertEqual(self.check().status,"UNAVAILABLE")

    def test_id_and_path_traversal(self):
        self.assertEqual(self.check("../outside").reason,"INVALID_OBSERVATION_ID")
        env=deepcopy(self.env)
        env["evidence"]["payload_ref_str"]="../../outside"
        self.manifest.write_bytes(canonical_json(env))
        self.assertEqual(self.check().reason,"NONCANONICAL_PAYLOAD_REF")

    def test_duplicate_keys_and_nonfinite_rejected(self):
        for bad in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1e999}',b'\xff'):
            self.manifest.write_bytes(bad)
            self.assertEqual(self.check().status,"REJECTED")

    def test_invalid_checkpoint_and_budgets(self):
        for kw in ({"max_payload_bytes":0},{"max_payload_bytes":True},
                   {"max_envelope_bytes":integrity.MAX_ENVELOPE_BYTES+1},
                   {"expected_checkpoint_sha256":"not-a-hash"}):
            self.assertEqual(self.check(**kw).status,"REJECTED")
        self.assertEqual(self.check(max_payload_bytes=1).reason,"PAYLOAD_BYTE_LIMIT")
        self.assertEqual(self.check(max_envelope_bytes=1).status,"REJECTED")

    def test_no_storewide_scan_and_unrelated_corruption_isolated(self):
        env,obs,path=self.camera()
        (self.root/env["evidence"]["payload_ref_str"]).write_bytes(b"corrupt")
        self.assertEqual(self.store.verify()["status"],"FAIL")
        with patch.object(EvidenceStore,"verify",side_effect=AssertionError("global scan")):
            self.assertEqual(self.check().status,"CHECKED")

    def test_readonly_and_no_creation_of_store(self):
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.check()
        integrity.audit_inventory(self.root)
        after={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before,after)
        missing=self.root.parent/"absent"
        self.assertEqual(integrity.verify_selected(missing,self.obs).status,"UNAVAILABLE")
        self.assertFalse(missing.exists())

    def test_cooperating_writer_lock_is_nonblocking(self):
        fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertEqual(self.check().status,"BUSY")
            report=integrity.audit_inventory(self.root)
            self.assertEqual(report.status,"INCOMPLETE")
            self.assertEqual(report.candidate_orphan_digests,())
        finally:
            os.close(fd)

    def test_selected_envelope_changes_between_reads(self):
        real=integrity._read
        done=False
        def changed(fd,name,limit):
            nonlocal done
            raw,identity=real(fd,name,limit)
            if name.endswith(".bin") and not done:
                done=True
                self.manifest.write_bytes(self.manifest.read_bytes()+b" ")
            return raw,identity
        with patch.object(integrity,"_read",side_effect=changed):
            result=self.check()
        self.assertEqual(result.status,"UNSTABLE")
        self.assertIsNone(result.checkpoint)

    def test_selected_payload_changes_after_first_read(self):
        real=integrity._read
        done=False
        def changed(fd,name,limit):
            nonlocal done
            raw,identity=real(fd,name,limit)
            if name.endswith(".bin") and not done:
                done=True
                self.payload.write_bytes(b"x"*len(raw))
            return raw,identity
        with patch.object(integrity,"_read",side_effect=changed):
            result=self.check()
        self.assertEqual(result.status,"UNSTABLE")
        self.assertIsNone(result.checkpoint)

    def test_symlink_hardlink_and_mode_rejected(self):
        raw=self.payload.read_bytes()
        outside=self.root.parent/"outside"
        outside.write_bytes(raw); outside.chmod(0o600)
        self.payload.unlink(); self.payload.symlink_to(outside)
        self.assertNotEqual(self.check().status,"CHECKED")
        self.payload.unlink(); os.link(outside,self.payload)
        self.assertNotEqual(self.check().status,"CHECKED")
        self.payload.unlink(); self.payload.write_bytes(raw);self.payload.chmod(0o644)
        self.assertNotEqual(self.check().status,"CHECKED")
        self.assertEqual(outside.read_bytes(),raw)

    def test_bucket_symlink_not_followed(self):
        bucket=self.payload.parent
        outside=self.root.parent/"bucket"
        bucket.rename(outside)
        bucket.symlink_to(outside,target_is_directory=True)
        self.assertNotEqual(self.check().status,"CHECKED")


class InventoryTests(unittest.TestCase):
    setUp=IntegrityTests.setUp
    camera=IntegrityTests.camera
    def test_inventory_shared_payload_and_orphan_missing(self):
        env1,obs1,_=self.camera()
        env2=self.store.record(data=b"synthetic camera bytes",source_id="second-camera",
            modality="rgb",reference_frame_id="frame.synthetic.camera",sequence=2,
            timestamp=receive_stamp(),media_type="image/jpeg",
            representation={"kind_str":"synthetic"})
        self.assertEqual(env1["evidence"]["payload_sha256_hex_str"],env2["evidence"]["payload_sha256_hex_str"])
        digest,_=self.store.put_payload(b"synthetic orphan")
        self.payload.unlink()
        result=integrity.audit_inventory(self.root)
        self.assertEqual(result.status,"COMPLETE_CANDIDATE_CENSUS",result)
        self.assertEqual(result.observation_manifests,3)
        self.assertEqual(result.payload_files,2)
        self.assertEqual(result.candidate_orphan_digests,(digest,))
        self.assertEqual(result.missing_payload_digests,(self.env["evidence"]["payload_sha256_hex_str"],))
        self.assertFalse(result.deletion_allowed)
        self.assertFalse(result.archive_integrity_verified)
        self.assertTrue(self.store._payload_path(digest).exists())

    def test_inventory_budget_exhaustion_no_partial_orphan_claim(self):
        self.store.put_payload(b"synthetic orphan")
        for kw in ({"max_entries":1},{"max_manifest_bytes":1},{"max_entries":True}):
            result=integrity.audit_inventory(self.root,**kw)
            self.assertEqual(result.status,"INCOMPLETE")
            self.assertEqual(result.candidate_orphan_digests,())
            self.assertEqual(result.candidate_orphan_count,0)

    def test_inventory_bad_manifest_no_orphan_claim(self):
        self.store.put_payload(b"synthetic orphan")
        self.manifest.write_bytes(b"broken")
        result=integrity.audit_inventory(self.root)
        self.assertEqual(result.status,"INCOMPLETE")
        self.assertEqual(result.candidate_orphan_digests,())

    def test_inventory_unknown_temp_or_file_no_orphan_claim(self):
        (self.store.observations/".incoming-synthetic").write_bytes(b"partial")
        result=integrity.audit_inventory(self.root)
        self.assertEqual(result.status,"INCOMPLETE")
        self.assertEqual(result.candidate_orphan_digests,())

    def test_inventory_detects_metadata_change_between_passes(self):
        real=integrity._read
        done=False
        def changed(fd,name,limit):
            nonlocal done
            raw,identity=real(fd,name,limit)
            if name.endswith(".json") and not done:
                done=True
                self.manifest.write_bytes(raw+b" ")
            return raw,identity
        with patch.object(integrity,"_read",side_effect=changed):
            r=integrity.audit_inventory(self.root)
        self.assertEqual(r.status,"INCOMPLETE")
        self.assertEqual(r.candidate_orphan_digests,())


if __name__=="__main__":
    unittest.main()
