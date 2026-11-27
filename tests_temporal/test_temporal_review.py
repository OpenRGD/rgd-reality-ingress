"""Synthetic A06 tests against actual A03/A04 source-owned stored evidence."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from reality_ingress.bounded_intake import preview_spool, apply_spool
from reality_ingress.consumer_ref import verified_ref_from_store
from reality_ingress.evidence import EvidenceStore
from reality_ingress.evidence_access import AccessResult, LocalEvidenceReader
from reality_ingress.generic import canonical_json, record_sample
from reality_ingress.interop_numeric import MAX_U64
from reality_ingress.temporal_review import (
    HostClock, PublisherClockClaim, HostOperationMark, TemporalReview, TemporalError,
    MAX_RECORDS, MAX_RECEIPT_AGE_NS,
)
from reality_ingress.timebase import receive_stamp

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tests_intake"))
from test_bounded_intake import scope_fixture,row_fixture

class Clock:
    def __init__(self): self.now=4_000_000_000
    def __call__(self): return self.now

class TemporalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=EvidenceStore(self.root/"store")
        self.scope=scope_fixture()
        self.row=row_fixture(self.scope,7,3_900_000_000)
        spool=self.root/"spool";spool.mkdir(mode=0o700)
        path=spool/self.scope.filename
        path.write_bytes(canonical_json(self.row)+b"\n");path.chmod(0o600)
        completed={"state":"COMPLETED","filename":self.scope.filename,"written":1,
                   "enqueued":1,"history_committed":False,"actuation_enabled":False}
        preview=preview_spool(spool,self.scope,completed)
        self.assertEqual(preview.status,"PREVIEW")
        applied=apply_spool(self.store,spool,self.scope,completed,
                            expected_spool_sha256=preview.spool_sha256)
        self.assertEqual(applied.status,"IMPORTED")
        path,=self.store.observations.glob("*.json")
        self.obs=path.stem
        self.ref=verified_ref_from_store(self.store,self.obs)
        self.context=HostClock("synthetic-host",self.ref["time"]["clock_domain_id"],
                               self.ref["time"]["boot_id"])
        self.claim=PublisherClockClaim(self.context,self.scope.source_id,"imu",
                                       self.scope.frame_id,self.scope.session_id)
        self.clock=Clock();self.owner=object()
        self.reader=LocalEvidenceReader(self.store.root,owner=self.owner)
        self.register(self.ref)
        self.review=self.new_review()
        schema=json.loads((ROOT/"contracts/temporal-assessment.v0.1-candidate.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        self.validator=Draft202012Validator(schema)

    def new_review(self,**kw):
        return TemporalReview(owner=self.owner,clock=self.context,clock_ns=self.clock,**kw)

    def register(self,ref,payload=True):
        self.reader.register_evidence(self.owner,canonical_json(ref),
            purposes=frozenset({"diagnostics"}),retention_seconds=120,
            metadata_consent=True,payload_consent=payload)

    def view(self,obs=None,payload=True):
        obs=self.obs if obs is None else obs
        ch=self.reader.grant(self.owner,obs,purpose="diagnostics",ttl_seconds=30,payload=payload)
        return self.reader.read(ch,obs,purpose="diagnostics",include_payload=payload)

    def additional(self,row):
        env,_=record_sample(self.store,row);obs=env["observation_id_str"]
        self.register(verified_ref_from_store(self.store,obs))
        return self.view(obs)

    def assess(self,view=None,**kw):
        return self.review.assess(self.owner,self.view() if view is None else view,**kw)

    def report(self,result):
        self.assertEqual(result.status,"ASSESSED",result)
        d=json.loads(result.assessment_json);self.validator.validate(d)
        for field in ("live_delivery","decision_eligible","source_verified","robot_binding_verified",
                      "history_committed","actuation_enabled"):
            self.assertFalse(d[field])
        self.assertIsNone(d["chronograf_anchor_ref"])
        self.assertIsNone(d["source_measurement_time"])
        self.assertIsNone(d["source_time_uncertainty_ns"])
        self.assertEqual(d["chronograf_status"],"UNRESOLVED")
        self.assertEqual(d["source_measurement_freshness"],"UNKNOWN")
        return d

    def test_original_receipt_preserved(self):
        view=self.view();before=(view.reference_json,view.payload_bytes)
        d=self.report(self.assess(view,publisher_clock=self.claim))
        self.assertEqual(d["observation_id"],self.obs)
        self.assertEqual(d["source_session_id"],self.scope.session_id)
        self.assertEqual(d["payload_sha256_hex"],self.ref["payload_sha256_hex"])
        for k in ("received_monotonic_ns","received_unix_estimate_ns","host_wall_pair_span_ns",
                  "receive_timestamp_method"):
            self.assertEqual(d["original_receipt"][k],self.row["temporal_binding"][k])
        self.assertEqual(d["receipt_age_ns"],100_000_000)
        self.assertEqual(d["receipt_age_state"],"RECENT_RECEIPT")
        self.assertEqual(d["receipt_clock_relation"],"HOST_SAME_BOOT_ASSERTED")
        self.assertEqual((view.reference_json,view.payload_bytes),before)

    def test_all_stored_modes_never_live(self):
        for mode in ("ARCHIVE_READ","IMPORT","REIMPORT","REPLAY","SYNTHETIC","UNKNOWN"):
            d=self.report(self.new_review().assess(self.owner,self.view(),
                          presentation=mode,publisher_clock=self.claim))
            self.assertEqual(d["presentation"],mode)
            self.assertEqual(d["receipt_age_state"],"RECENT_RECEIPT")
        self.assertEqual(self.assess(presentation="LIVE").reason,"INVALID_PRESENTATION")

    def test_same_boot_label_without_assertion_unknown(self):
        d=self.report(self.assess())
        self.assertIsNone(d["receipt_age_ns"])
        self.assertEqual(d["receipt_clock_relation"],"NOT_ESTABLISHED")

    def test_cross_host_even_same_boot_unknown(self):
        claim=replace(self.claim,clock=replace(self.context,host_label="remote-host"))
        d=self.report(self.assess(publisher_clock=claim))
        self.assertIsNone(d["receipt_age_ns"])
        self.assertEqual(d["publisher_host_label"],"remote-host")

    def test_boot_domain_session_source_frame_mismatch(self):
        for claim in (replace(self.claim,clock=replace(self.context,boot_id="other-boot")),
                      replace(self.claim,clock=replace(self.context,clock_domain_id="other-domain")),
                      replace(self.claim,session_id="b"*32),replace(self.claim,source_id="other"),
                      replace(self.claim,reference_frame_id="other-frame")):
            with self.subTest(claim=claim):
                d=self.report(self.new_review().assess(self.owner,self.view(),publisher_clock=claim))
                self.assertIsNone(d["receipt_age_ns"])

    def test_stale_boundary(self):
        self.clock.now=6_900_000_000
        d=self.report(self.assess(publisher_clock=self.claim))
        self.assertEqual(d["receipt_age_ns"],3_000_000_000)
        self.assertEqual(d["receipt_age_state"],"STALE_RECEIPT")

    def test_future_receipt_rejected_if_comparable(self):
        self.clock.now=3_899_999_999
        r=self.assess(publisher_clock=self.claim)
        self.assertEqual(r.reason,"FUTURE_ORIGINAL_RECEIPT")
        self.assertIsNone(r.assessment_json)
        self.assertEqual(self.review.stats(self.owner)["records"],0)
        self.assertIsNone(self.report(self.assess())["receipt_age_ns"])

    def test_metadata_does_not_invent_session_or_method(self):
        d=self.report(self.assess(self.view(payload=False),publisher_clock=self.claim))
        self.assertIsNone(d["source_session_id"])
        self.assertIsNone(d["receipt_age_ns"])
        self.assertIsNone(d["original_receipt"]["receive_timestamp_method"])
        self.assertIsNone(d["original_receipt"]["received_unix_estimate_ns"])
        self.assertEqual(d["original_receipt"]["received_monotonic_ns"],3_900_000_000)

    def test_legacy_camera_metadata_remains_unknown(self):
        env=self.store.record(data=b"synthetic camera",source_id="camera",modality="rgb",
            reference_frame_id="frame.camera",sequence=1,timestamp=receive_stamp(),
            media_type="image/jpeg",representation={"kind_str":"synthetic"})
        ref=verified_ref_from_store(self.store,env["observation_id_str"]);self.register(ref,payload=False)
        d=self.report(self.assess(self.view(ref["observation_id"],payload=False),publisher_clock=self.claim))
        self.assertIsNone(d["source_session_id"]);self.assertIsNone(d["receipt_age_ns"])

    def test_import_and_verify_marks_separate(self):
        self.clock.now=10_000_000_000
        d=self.report(self.assess(presentation="IMPORT",publisher_clock=self.claim,
              import_mark=HostOperationMark("IMPORT",self.context,self.clock.now-10),
              verification_mark=HostOperationMark("VERIFY",self.context,self.clock.now)))
        self.assertEqual(d["receipt_age_ns"],6_100_000_000)
        self.assertEqual(d["receipt_age_state"],"STALE_RECEIPT")
        self.assertEqual(d["import_mark"]["monotonic_ns"],self.clock.now-10)
        self.assertEqual(d["verification_mark"]["quality"],"HOST_REPORTED")
        self.assertEqual(d["original_receipt"]["received_monotonic_ns"],3_900_000_000)

    def test_missing_marks_and_role_mismatch(self):
        d=self.report(self.assess());self.assertIsNone(d["import_mark"]);self.assertIsNone(d["verification_mark"])
        r=self.new_review().assess(self.owner,self.view(),import_mark=HostOperationMark("VERIFY",self.context,0))
        self.assertEqual(r.reason,"OPERATION_ROLE_MISMATCH")

    def test_foreign_operation_mark_not_compared(self):
        foreign=replace(self.context,host_label="different-host")
        d=self.report(self.assess(import_mark=HostOperationMark("IMPORT",foreign,MAX_U64)))
        self.assertEqual(d["import_mark"]["monotonic_ns"],MAX_U64)
        self.assertIsNone(d["receipt_age_ns"])
        r=self.new_review().assess(self.owner,self.view(),
            import_mark=HostOperationMark("IMPORT",self.context,self.clock.now+1))
        self.assertEqual(r.reason,"FUTURE_OPERATION_MARK")

    def test_reimport_and_replay_duplicates_inert(self):
        first=self.assess(publisher_clock=self.claim);before=first.assessment_json
        self.report(first);self.clock.now+=10_000_000_000
        for mode in ("REIMPORT","REPLAY","SYNTHETIC","ARCHIVE_READ"):
            r=self.assess(presentation=mode,publisher_clock=self.claim)
            self.assertEqual(r.status,"DUPLICATE");self.assertIsNone(r.assessment_json)
        self.assertEqual(self.review.stats(self.owner)["records"],1)
        self.assertEqual(first.assessment_json,before)

    def test_metadata_then_checked_view_is_inert(self):
        meta=self.view(payload=False);payload=self.view()
        self.report(self.assess(meta))
        r=self.assess(payload,publisher_clock=self.claim)
        self.assertEqual(r.status,"DUPLICATE");self.assertIsNone(r.assessment_json)
        self.assertEqual(self.review.stats(self.owner)["bound_keys"],1)
        self.assertEqual(json.loads(meta.reference_json)["integrity_status"],"not_verified")

    def test_same_id_different_reference_collision(self):
        meta=self.view(payload=False);self.report(self.assess(meta))
        ref=json.loads(meta.reference_json);ref["source_id"]="forged"
        self.assertEqual(self.assess(replace(meta,reference_json=canonical_json(ref))).reason,
                         "OBSERVATION_ID_COLLISION")

    def test_same_session_sequence_content_conflict(self):
        self.report(self.assess());row=deepcopy(self.row)
        row["payload"]["console_ingest_sample"]["temperature_c"]=22.0
        self.assertEqual(self.assess(self.additional(row)).reason,"SESSION_SEQUENCE_COLLISION")

    def test_out_of_order_historical(self):
        self.report(self.assess())
        d=self.report(self.assess(self.additional(row_fixture(self.scope,6,3_800_000_000)),
                                  presentation="REPLAY",publisher_clock=self.claim))
        self.assertEqual(d["sequence_relation"],"OUT_OF_ORDER")
        d=self.report(self.assess(self.additional(row_fixture(self.scope,8,3_950_000_000))))
        self.assertEqual(d["sequence_relation"],"IN_ORDER")

    def test_receipt_order_conflicts(self):
        self.report(self.assess())
        for seq,mono in ((8,3_800_000_000),(6,3_950_000_000)):
            self.assertEqual(self.assess(self.additional(row_fixture(self.scope,seq,mono))).reason,
                             "SOURCE_RECEIPT_ORDER_CONFLICT")

    def test_new_session_and_boot_scope_distinct(self):
        self.report(self.assess())
        scope=replace(self.scope,session_id="b"*32,boot_id="ac7e69f1-4482-4bfc-8bf9-615f56cf31b0")
        d=self.report(self.assess(self.additional(row_fixture(scope,1,1)),publisher_clock=self.claim))
        self.assertEqual(d["sequence_relation"],"FIRST_IN_SCOPE")
        self.assertIsNone(d["receipt_age_ns"])

    def test_blocked_unavailable_voice_report_rejected(self):
        for view in (AccessResult("BLOCKED","NOT_AUTHORIZED","DENIED"),
                     AccessResult("UNAVAILABLE","MISSING","MISSING"),
                     AccessResult("REFERENCE_ONLY","UNKNOWN","VOICE",
                         reference_json=b'{"schema_version":"voice.audio-segment-closed-report.v0.1-candidate"}')):
            self.assertEqual(self.assess(view).status,"REJECTED")
        self.assertEqual(self.review.stats(self.owner)["records"],0)

    def test_payload_tamper_rejected_even_on_duplicate(self):
        good=self.view();self.report(self.assess(good))
        self.assertEqual(self.assess(replace(good,payload_bytes=good.payload_bytes+b" ")).status,"REJECTED")
        row=json.loads(good.payload_bytes);row["payload"]["console_ingest_sample"]["temperature_c"]=22
        self.assertEqual(self.assess(replace(good,payload_bytes=canonical_json(row))).status,"REJECTED")

    def test_false_authority(self):
        view=self.view();self.assertEqual(self.assess(replace(view,source_verified=True)).status,"REJECTED")
        ref=json.loads(view.reference_json);ref["time"]["chronograf_anchor_ref"]="invented"
        self.assertEqual(self.assess(replace(view,reference_json=canonical_json(ref))).status,"REJECTED")

    def test_wrong_owner_no_clock(self):
        view=self.view()
        with patch.object(self.review,"_clock",side_effect=AssertionError("unauthorized clock")):
            r=self.review.assess(object(),view)
        self.assertEqual(r.status,"BLOCKED");self.assertIsNone(r.assessment_json)

    def test_clock_regression_closes(self):
        self.report(self.assess());self.clock.now-=1
        self.assertEqual(self.assess().reason,"ASSESSMENT_CLOCK_INVALID_OR_REGRESSED")
        self.assertTrue(self.review.stats(self.owner)["closed"])
        self.clock.now+=100;self.assertEqual(self.assess().reason,"REVIEW_CLOSED")

    def test_backpressure_no_eviction(self):
        self.review=self.new_review(max_records=1);self.report(self.assess())
        self.assertEqual(self.assess(self.additional(row_fixture(self.scope,8,3_950_000_000))).reason,
                         "REVIEW_BACKPRESSURE")
        self.assertEqual(self.assess().status,"DUPLICATE")
        for kw in ({"max_records":0},{"max_records":MAX_RECORDS+1},{"max_records":True},
                   {"max_receipt_age_ns":MAX_RECEIPT_AGE_NS+1}):
            with self.assertRaises(TemporalError): self.new_review(**kw)

    def test_exact_u64(self):
        for value in (True,-1,1.0,MAX_U64+1,"1"):
            with self.assertRaises(TemporalError): HostOperationMark("IMPORT",self.context,value)
        self.clock.now=MAX_U64
        d=self.report(self.assess(publisher_clock=self.claim))
        self.assertEqual(d["assessment_monotonic_ns"],MAX_U64)
        self.assertEqual(d["receipt_age_ns"],MAX_U64-3_900_000_000)

    def test_closed_schema_and_no_unqualified_age(self):
        d=self.report(self.assess())
        for changed in (dict(d,live_delivery=True),dict(d,chronograf_status="QUALIFIED"),
                        dict(d,receipt_age_ns=1),dict(d,receipt_age_state="RECENT_RECEIPT"),dict(d,extra=1)):
            self.assertFalse(self.validator.is_valid(changed))

    def test_no_store_lookup_or_write(self):
        view=self.view()
        before={p.relative_to(self.store.root):p.read_bytes() for p in self.store.root.rglob("*") if p.is_file()}
        with patch.object(EvidenceStore,"verify",side_effect=AssertionError("scan")), \
             patch.object(EvidenceStore,"get_observation",side_effect=AssertionError("lookup")):
            result=self.assess(view)
        self.report(result);self.assertNotIn("payload_ref_str",result.assessment_json.decode())
        self.assertNotIn(self.obs,repr(result))
        self.assertEqual(before,{p.relative_to(self.store.root):p.read_bytes()
                                  for p in self.store.root.rglob("*") if p.is_file()})

if __name__=="__main__":
    unittest.main()
