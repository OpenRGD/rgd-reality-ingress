"""RI-A04 tests using synthetic actual A03/legacy stored content only."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from reality_ingress import evidence_access as access
from reality_ingress.bounded_intake import preview_spool, apply_spool
from reality_ingress.consumer_ref import verified_ref_from_store
from reality_ingress.evidence import EvidenceStore
from reality_ingress.generic import canonical_json, record_sample
from reality_ingress.timebase import receive_stamp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests_intake"))
from test_bounded_intake import scope_fixture, row_fixture

PURPOSE = "diagnostics"


class Clock:
    def __init__(self): self.now = 1_000_000_000
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds * 1_000_000_000


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = EvidenceStore(self.root / "store")
        self.scope = scope_fixture()
        self.row = row_fixture(self.scope)
        spool = self.root / "spool"
        spool.mkdir(mode=0o700)
        path = spool / self.scope.filename
        path.write_bytes(canonical_json(self.row) + b"\n")
        path.chmod(0o600)
        completed = {"state":"COMPLETED", "filename":self.scope.filename,
                     "written":1, "enqueued":1, "history_committed":False,
                     "actuation_enabled":False}
        preview = preview_spool(spool, self.scope, completed)
        self.assertEqual(preview.status, "PREVIEW")
        result = apply_spool(self.store, spool, self.scope, completed,
                             expected_spool_sha256=preview.spool_sha256)
        self.assertEqual(result.status, "IMPORTED")
        obs_path, = self.store.observations.glob("*.json")
        self.obs = obs_path.stem
        self.env = self.store.get_observation(self.obs)
        self.ref = verified_ref_from_store(self.store,self.obs)
        self.payload_path = self.store.root/self.env["evidence"]["payload_ref_str"]
        self.clock, self.owner = Clock(), object()
        self.reader = access.LocalEvidenceReader(self.store.root, owner=self.owner, clock_ns=self.clock)

    def register(self, *, ref=None, metadata=True, payload=True, retention=60,
                 purposes=frozenset({PURPOSE,"cognition"})):
        self.reader.register_evidence(self.owner, canonical_json(self.ref if ref is None else ref),
            purposes=purposes, retention_seconds=retention, metadata_consent=metadata,
            payload_consent=payload)

    def grant(self, *, payload=False, ttl=30, **kwargs):
        return self.reader.grant(self.owner,self.obs,purpose=PURPOSE,payload=payload,
                                 ttl_seconds=ttl,**kwargs)

    def read(self, ch, *, payload=False, purpose=PURPOSE, obs=None):
        return self.reader.read(ch,self.obs if obs is None else obs,purpose=purpose,include_payload=payload)

    def no_bytes(self, result):
        self.assertIsNone(result.reference_json)
        self.assertIsNone(result.payload_bytes)
        self.assertFalse(result.erasure_verified)
        self.assertNotIn(self.obs,repr(result))
        self.assertNotIn(str(self.root),repr(result))

    def test_default_deny_before_any_io_and_no_existence_oracle(self):
        with patch.object(self.reader,"_read_at",side_effect=AssertionError("unauthorized IO")):
            results = [self.read(object()),self.read(object(),obs="obs_"+"0"*32),
                       self.read(self.obs),self.read(self.ref)]
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(results[0].availability,"NOT_AUTHORIZED")
        self.no_bytes(results[0])

    def test_owner_required_and_no_grant_from_ref(self):
        with self.assertRaises(access.AccessError):
            self.reader.register_evidence(object(),canonical_json(self.ref),
                purposes=frozenset({PURPOSE}),retention_seconds=30,metadata_consent=True)
        with self.assertRaises(access.AccessError):
            self.grant()
        self.register()
        with self.assertRaises(access.AccessError):
            self.reader.grant(object(),self.obs,purpose=PURPOSE,ttl_seconds=10)
        with self.assertRaises(access.AccessError):
            self.reader.stats(object())

    def test_metadata_only_no_payload_probe_and_no_inherited_hash_claim(self):
        self.register(payload=False)
        ch=self.grant(max_reads=2)
        with patch.object(self.reader,"_read_at",wraps=self.reader._read_at) as io:
            result=self.read(ch)
            self.assertEqual(io.call_count,1)
            self.assertEqual(io.call_args.args[0],self.store.observations)
        self.assertEqual((result.status,result.availability),("REFERENCE_ONLY","UNKNOWN"))
        ref=json.loads(result.reference_json)
        self.assertEqual(ref,dict(self.ref,integrity_status="not_verified"))
        self.assertIsNone(result.payload_bytes)
        self.assertEqual(result.integrity_scope,"NOT_CHECKED")
        with patch.object(self.reader,"_read_at",side_effect=AssertionError("payload denied")):
            self.no_bytes(self.read(ch,payload=True))

    def test_explicit_payload_exact_bytes_and_no_envelope_path(self):
        self.register()
        ch=self.grant(payload=True)
        result=self.read(ch,payload=True)
        self.assertEqual((result.status,result.availability),("PAYLOAD_RESOLVED","AVAILABLE"))
        self.assertEqual(result.integrity_scope,"SELECTED_LOCAL_SNAPSHOT")
        self.assertEqual(result.payload_bytes,canonical_json(self.row))
        self.assertEqual(json.loads(result.reference_json),self.ref)
        schema=json.loads((ROOT/"contracts/consumer-observation-ref.v0.1-candidate.schema.json").read_text())
        Draft202012Validator(schema).validate(json.loads(result.reference_json))
        self.assertNotIn("payload_ref_str",result.reference_json.decode())
        self.assertFalse(result.source_verified)
        self.assertFalse(result.robot_binding_verified)
        self.assertFalse(result.history_committed)
        self.assertFalse(result.actuation_enabled)
        self.assertNotIn("payload_bytes=b",repr(result))

    def test_no_global_scan_or_legacy_verify(self):
        self.register()
        ch=self.grant(payload=True)
        with patch.object(EvidenceStore,"verify",side_effect=AssertionError("global scan")):
            self.assertEqual(self.read(ch,payload=True).status,"PAYLOAD_RESOLVED")

    def test_wrong_id_purpose_or_scope_denied_without_io(self):
        self.register()
        ch=self.grant()
        with patch.object(self.reader,"_read_at",side_effect=AssertionError("denied IO")):
            for r in (self.read(ch,obs="obs_"+"b"*32),self.read(ch,purpose="cognition"),
                      self.read(ch,payload=True),self.read(ch,payload=1)):
                self.assertEqual(r.availability,"NOT_AUTHORIZED")
                self.no_bytes(r)

    def test_consent_defaults_deny_and_payload_requires_metadata(self):
        with self.assertRaises(access.AccessError):
            self.register(metadata=False,payload=True)
        self.register(metadata=False,payload=False)
        with self.assertRaises(access.AccessError): self.grant()
        with self.assertRaises(access.AccessError): self.grant(payload=True)

    def test_metadata_consent_not_payload_consent(self):
        self.register(payload=False)
        with self.assertRaises(access.AccessError): self.grant(payload=True)
        self.assertEqual(self.read(self.grant()).status,"REFERENCE_ONLY")

    def test_explicit_purpose_allowlist(self):
        self.register(purposes=frozenset({"calibration"}))
        with self.assertRaises(access.AccessError): self.grant()

    def test_revocation_is_one_way_for_channel(self):
        self.register()
        ch=self.grant(payload=True,max_reads=3)
        self.assertEqual(self.read(ch,payload=True).status,"PAYLOAD_RESOLVED")
        self.reader.revoke(self.owner,ch)
        with patch.object(self.reader,"_read_at",side_effect=AssertionError("revoked IO")):
            self.no_bytes(self.read(ch,payload=True))
        with self.assertRaises(access.AccessError): self.reader.revoke(object(),ch)

    def test_lease_expiry_at_boundary(self):
        self.register()
        ch=self.grant(ttl=2)
        self.clock.advance(2)
        with patch.object(self.reader,"_read_at",side_effect=AssertionError("expired IO")):
            r=self.read(ch)
        self.assertEqual(r.reason,"LEASE_EXPIRED")
        self.no_bytes(r)

    def test_retention_deadline_caps_lease_and_cannot_extend(self):
        self.register(retention=2)
        ch=self.grant(payload=True,ttl=30)
        self.clock.advance(2)
        r=self.read(ch,payload=True)
        self.assertEqual(r.availability,"EXPIRED")
        self.no_bytes(r)
        with self.assertRaises(access.AccessError): self.grant()
        with self.assertRaises(access.AccessError): self.register(retention=300)
        self.assertTrue(self.payload_path.exists())

    def test_expiry_while_resolving_discards_bytes(self):
        self.register()
        ch=self.grant(payload=True,ttl=1)
        resolve=self.reader._resolve
        def slow(*args):
            result=resolve(*args)
            self.clock.advance(1)
            return result
        with patch.object(self.reader,"_resolve",side_effect=slow):
            r=self.read(ch,payload=True)
        self.assertEqual(r.reason,"LEASE_EXPIRED")
        self.no_bytes(r)
        self.assertEqual(self.reader.stats(self.owner)["payload_bytes_released"],0)

    def test_clock_regression_latches_reader_closed(self):
        self.register()
        ch=self.grant()
        self.clock.now-=1
        self.no_bytes(self.read(ch))
        self.assertTrue(self.reader.stats(self.owner)["closed"])
        self.clock.advance(20)
        self.no_bytes(self.read(ch))

    def test_payload_withhold_does_not_grant_redacted_copy(self):
        self.register()
        ch=self.grant(payload=True,max_reads=2)
        self.reader.withhold(self.owner,self.obs,scope="payload",state="REDACTED")
        self.no_bytes(self.read(ch,payload=True))
        self.assertEqual(self.read(ch,payload=True).availability,"REDACTED")
        self.assertEqual(self.read(ch).status,"REFERENCE_ONLY")
        self.assertTrue(self.payload_path.exists())

    def test_metadata_withhold_blocks_both_and_no_erasure_proof(self):
        self.register()
        ch=self.grant(payload=True)
        self.reader.withhold(self.owner,self.obs,scope="metadata",state="ERASURE_REPORTED")
        for payload in (False,True):
            r=self.read(ch,payload=payload)
            self.assertEqual(r.availability,"ERASURE_REPORTED")
            self.no_bytes(r)
        self.assertTrue(self.payload_path.exists())
        with self.assertRaises(access.AccessError):
            self.reader.withhold(self.owner,self.obs,scope="metadata",state="RESTRICTED")

    def test_missing_envelope_only_after_authorization(self):
        self.register()
        ch=self.grant()
        (self.store.observations/(self.obs+".json")).unlink()
        self.assertEqual(self.read(object()).availability,"NOT_AUTHORIZED")
        r=self.read(ch)
        self.assertEqual(r.availability,"MISSING")
        self.no_bytes(r)

    def test_missing_payload_metadata_remains_unknown(self):
        self.register()
        ch=self.grant(payload=True,max_reads=2)
        self.payload_path.unlink()
        self.assertEqual(self.read(ch).availability,"UNKNOWN")
        r=self.read(ch,payload=True)
        self.assertEqual(r.availability,"MISSING")
        self.no_bytes(r)

    def test_corrupt_payload_no_ref_or_bytes(self):
        self.register()
        ch=self.grant(payload=True)
        self.payload_path.write_bytes(b"x"*self.ref["payload_size_bytes"])
        r=self.read(ch,payload=True)
        self.assertEqual(r.availability,"CORRUPT_OR_UNSUPPORTED")
        self.no_bytes(r)

    def test_corrupt_envelope_or_reference_pin_no_release(self):
        self.register()
        ch=self.grant(max_reads=2)
        env=deepcopy(self.env)
        env["source"]["session_id_str"]="b"*32
        (self.store.observations/(self.obs+".json")).write_bytes(canonical_json(env))
        r=self.read(ch)
        self.assertEqual(r.availability,"CORRUPT_OR_UNSUPPORTED")
        self.no_bytes(r)

    def test_reference_digest_scope_not_replaceable(self):
        self.register(ref=dict(self.ref,payload_sha256_hex="b"*64))
        r=self.read(self.grant())
        self.assertEqual(r.availability,"CORRUPT_OR_UNSUPPORTED")
        self.no_bytes(r)

    def test_payload_budget_rejects_before_media_io(self):
        self.register()
        ch=self.grant(payload=True,max_payload_bytes=1)
        with patch.object(self.reader,"_read_at",wraps=self.reader._read_at) as io:
            r=self.read(ch,payload=True)
            self.assertEqual(io.call_count,1)
        self.assertEqual(r.reason,"PAYLOAD_BYTE_BUDGET")
        self.no_bytes(r)

    def test_read_and_cumulative_release_budget(self):
        self.register()
        size=self.ref["payload_size_bytes"]
        ch=self.grant(payload=True,max_reads=3,max_total_payload_bytes=size)
        self.assertEqual(self.read(ch,payload=True).availability,"AVAILABLE")
        self.assertEqual(self.read(ch,payload=True).reason,"PAYLOAD_BYTE_BUDGET")
        self.assertEqual(self.read(ch).status,"REFERENCE_ONLY")
        self.assertEqual(self.read(ch).reason,"READ_BUDGET_EXHAUSTED")
        self.assertEqual(self.reader.stats(self.owner)["payload_bytes_released"],size)

    def test_failed_read_charges_attempt_not_bytes(self):
        self.register()
        ch=self.grant(payload=True)
        self.payload_path.unlink()
        self.assertEqual(self.read(ch,payload=True).availability,"MISSING")
        self.assertEqual(self.read(ch,payload=True).reason,"READ_BUDGET_EXHAUSTED")
        self.assertEqual(self.reader.stats(self.owner)["payload_bytes_released"],0)

    def test_no_path_resolution_from_payload_ref(self):
        self.register()
        ch=self.grant(payload=True)
        env=deepcopy(self.env)
        env["evidence"]["payload_ref_str"]="../../outside"
        (self.store.observations/(self.obs+".json")).write_bytes(canonical_json(env))
        self.no_bytes(self.read(ch,payload=True))

    def test_symlink_and_mode_reject_without_release(self):
        self.register()
        ch=self.grant(payload=True,max_reads=2)
        raw=self.payload_path.read_bytes()
        outside=self.root/"outside"
        outside.write_bytes(raw); outside.chmod(0o600)
        self.payload_path.unlink(); self.payload_path.symlink_to(outside)
        self.no_bytes(self.read(ch,payload=True))
        self.payload_path.unlink(); self.payload_path.write_bytes(raw)
        self.payload_path.chmod(0o644)
        self.no_bytes(self.read(ch,payload=True))
        self.assertEqual(outside.read_bytes(),raw)

    def test_camera_metadata_only_no_camera_payload(self):
        env=self.store.record(data=b"synthetic image",source_id="camera",modality="rgb",
             reference_frame_id="frame.camera",sequence=1,timestamp=receive_stamp(),
             media_type="image/jpeg",representation={"kind_str":"synthetic"})
        ref=verified_ref_from_store(self.store,env["observation_id_str"])
        with self.assertRaises(access.AccessError): self.register(ref=ref,payload=True)
        self.register(ref=ref,payload=False)
        ch=self.reader.grant(self.owner,ref["observation_id"],purpose=PURPOSE,ttl_seconds=10)
        r=self.read(ch,obs=ref["observation_id"])
        self.assertEqual(r.status,"REFERENCE_ONLY")
        self.assertEqual(r.availability,"UNKNOWN")

    def test_audio_and_unsupported_refs_rejected_before_policy(self):
        for modified in (dict(self.ref,modality="audio",payload_media_type="audio/wav"),
                         dict(self.ref,source_verified=True),
                         dict(self.ref,sample_sequence=2**64),
                         dict(self.ref,extra="unknown")):
            with self.subTest(field=modified),self.assertRaises(access.AccessError):
                self.register(ref=modified)

    def test_invalid_policy_and_lease_limits(self):
        for args in ({"retention":0},{"retention":86401},{"retention":True},
                     {"purposes":frozenset({"remote_upload"})}):
            with self.subTest(args=args),self.assertRaises(access.AccessError):
                self.register(**args)
        self.register()
        for args in ({"ttl":3601},{"ttl":0},{"max_reads":61},{"max_reads":True},
                     {"max_payload_bytes":4097},{"max_total_payload_bytes":262145}):
            with self.subTest(args=args),self.assertRaises(access.AccessError):
                self.grant(**args)

    def test_grant_table_bounded_no_reuse_of_revoked_channel(self):
        self.register()
        channels=[self.grant() for _ in range(access.MAX_CHANNELS)]
        self.reader.revoke(self.owner,channels[0])
        with self.assertRaises(access.AccessError): self.grant()
        self.assertEqual(self.reader.stats(self.owner)["channels"],access.MAX_CHANNELS)

    def test_close_blocks_existing_and_future_access(self):
        self.register()
        ch=self.grant()
        self.reader.close(self.owner)
        self.no_bytes(self.read(ch))
        with self.assertRaises(access.AccessError): self.grant()

    def test_read_does_not_write_store_and_stats_redacted(self):
        self.register()
        ch=self.grant(payload=True)
        before={p.relative_to(self.store.root):p.read_bytes()
                for p in self.store.root.rglob("*") if p.is_file()}
        self.read(ch,payload=True)
        after={p.relative_to(self.store.root):p.read_bytes()
               for p in self.store.root.rglob("*") if p.is_file()}
        self.assertEqual(before,after)
        summary=self.reader.stats(self.owner)
        self.assertEqual(summary["payload_releases"],1)
        self.assertNotIn(self.obs,str(summary))

    def test_reader_constructor_does_not_create_store(self):
        missing=self.root/"absent"
        with self.assertRaises((OSError,ValueError,access.IntakeError)):
            access.LocalEvidenceReader(missing,owner=self.owner)
        self.assertFalse(missing.exists())


if __name__=="__main__":
    unittest.main()
