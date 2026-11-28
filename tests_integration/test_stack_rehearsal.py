"""Actual RI A03->A04->A05->A06 synthetic rehearsal; no hardware or network."""
from dataclasses import asdict
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from reality_ingress.bounded_intake import preview_spool, apply_spool, GENERALIZED
from reality_ingress.evidence import EvidenceStore
from reality_ingress.evidence_access import LocalEvidenceReader
from reality_ingress.integrity_inspection import verify_selected, audit_inventory
from reality_ingress.consumer_ref import verified_ref_from_store
from reality_ingress.generic import canonical_json, record_sample
from reality_ingress.temporal_review import HostClock, TemporalReview
from scripts import pilot_review

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tests_intake"))
from test_bounded_intake import scope_fixture,row_fixture

class RehearsalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.spool=self.root/"spool";self.spool.mkdir(mode=0o700)
        self.scope=scope_fixture()
        self.rows=[row_fixture(self.scope,1,1_000_000_000),
                   row_fixture(self.scope,3,3_000_000_000)]
        self.prepare(self.scope,self.rows)
        self.owner=object()
        self.now=5_000_000_000
        self.reader=LocalEvidenceReader(self.store.root,owner=self.owner,clock_ns=lambda:self.now)
        self.review=TemporalReview(owner=self.owner,
             clock=HostClock("synthetic-review-host","synthetic-review-domain","synthetic-boot"),
             clock_ns=lambda:self.now)
        self.ids=tuple(sorted(p.stem for p in self.store.observations.glob("obs_*.json")))
        self.assertEqual(len(self.ids),2)
        self.checkpoints={}
        for obs in self.ids:
            cp=verify_selected(self.store.root,obs)
            self.assertEqual(cp.status,"CHECKED")
            self.assertEqual(cp.checkpoint_status,"NEW_BASELINE_ONLY")
            self.checkpoints[obs]=cp.checkpoint.sha256
            self.reader.register_evidence(self.owner,
                canonical_json(verified_ref_from_store(self.store,obs)),
                purposes=frozenset({"diagnostics"}),retention_seconds=60,
                metadata_consent=True,payload_consent=True)
        self.obs=self.ids[0]

    def prepare(self,scope,rows):
        raw=b"".join(canonical_json(row)+b"\n" for row in rows)
        path=self.spool/scope.filename;path.write_bytes(raw);path.chmod(0o600)
        self.completed={"state":"COMPLETED","filename":scope.filename,
            "written":len(rows),"enqueued":len(rows),"history_committed":False,
            "actuation_enabled":False,"written_bytes":len(raw)}
        self.preview=preview_spool(self.spool,scope,self.completed)
        self.assertEqual(self.preview.status,"PREVIEW")
        self.store=EvidenceStore(self.root/"store")
        result=apply_spool(self.store,self.spool,scope,self.completed,
                           expected_spool_sha256=self.preview.spool_sha256)
        self.assertEqual(result.status,"IMPORTED")
        self.assertEqual(result.created,len(rows))

    def grant(self,obs=None,**kw):
        opts=dict(payload=True,ttl_seconds=30,max_reads=3);opts.update(kw)
        return self.reader.grant(self.owner,self.obs if obs is None else obs,
                                 purpose="diagnostics",**opts)
    def gate(self,ch,obs=None,**kw):
        obs=self.obs if obs is None else obs
        opts=dict(expected_checkpoint_sha256=self.checkpoints[obs]);opts.update(kw)
        return pilot_review.review_record(self.reader,self.review,self.owner,ch,obs,**opts)

    def test_complete_chain_all_records_and_no_writes_on_review(self):
        before={p.relative_to(self.store.root):p.read_bytes() for p in self.store.root.rglob("*") if p.is_file()}
        for obs in self.ids:
            result=self.gate(self.grant(obs),obs)
            self.assertEqual(result.status,"REVIEWED",result)
            self.assertEqual(result.receipt_age_state,"UNKNOWN")
            self.assertFalse(result.live_delivery)
            self.assertFalse(result.physical_authorized)
            self.assertEqual(set(asdict(result)),{"status","stage","reason","receipt_age_state",
                                                "live_delivery","physical_authorized"})
        self.assertEqual(self.review.stats(self.owner)["records"],2)
        self.assertEqual(before,{p.relative_to(self.store.root):p.read_bytes()
                                for p in self.store.root.rglob("*") if p.is_file()})

    def test_reimport_and_replay_do_not_create_new_evidence_or_assessment(self):
        ch=self.grant()
        self.assertEqual(self.gate(ch).status,"REVIEWED")
        result=apply_spool(self.store,self.spool,self.scope,self.completed,
                           expected_spool_sha256=self.preview.spool_sha256)
        self.assertEqual((result.created,result.already_present),(0,2))
        self.now+=10_000_000_000
        self.assertEqual(self.gate(ch,presentation="REIMPORT").status,"DUPLICATE")
        self.assertEqual(self.gate(ch,presentation="REPLAY").status,"DUPLICATE")
        self.assertEqual(self.review.stats(self.owner)["records"],1)

    def test_denial_revocation_and_metadata_only_never_run_a05_or_a06(self):
        revoked=self.grant();self.reader.revoke(self.owner,revoked)
        metadata=self.grant(payload=False)
        with patch.object(pilot_review,"verify_selected",side_effect=AssertionError("denied inspection")):
            for ch in (object(),revoked,metadata):
                self.assertEqual(self.gate(ch).stage,"A04")
        self.assertEqual(self.review.stats(self.owner)["records"],0)

    def test_expired_channel_no_temporal_state(self):
        ch=self.grant(ttl_seconds=1)
        self.now+=1_000_000_000
        self.assertEqual(self.gate(ch).stage,"A04")
        self.assertEqual(self.review.stats(self.owner)["records"],0)

    def test_wrong_owner_and_missing_checkpoint_block_before_read(self):
        ch=self.grant()
        with patch.object(self.reader,"read",side_effect=AssertionError("unauthorized read")):
            r=pilot_review.review_record(self.reader,self.review,object(),ch,self.obs,
                  expected_checkpoint_sha256=self.checkpoints[self.obs])
            self.assertEqual(r.stage,"CONFIGURATION")
            self.assertEqual(self.gate(ch,expected_checkpoint_sha256=None).stage,"CONFIGURATION")
            self.assertEqual(self.gate(ch,presentation="LIVE").stage,"CONFIGURATION")

    def test_semantic_envelope_rewrite_detected_by_a05_before_a06(self):
        # A04's generic semantic checks deliberately accept this same object.
        env=self.store.get_observation(self.obs)
        (self.store.observations/(self.obs+".json")).write_bytes(canonical_json(env))
        r=self.gate(self.grant())
        self.assertEqual((r.stage,r.reason),("A05","CHECKPOINT_MISMATCH"))
        self.assertEqual(self.review.stats(self.owner)["records"],0)

    def test_payload_tamper_denied_before_a05_or_temporal(self):
        env=self.store.get_observation(self.obs)
        path=self.store.root/env["evidence"]["payload_ref_str"]
        path.write_bytes(b"x"*path.stat().st_size)
        with patch.object(pilot_review,"verify_selected",side_effect=AssertionError("invalid inspection")):
            self.assertEqual(self.gate(self.grant()).stage,"A04")
        self.assertEqual(self.review.stats(self.owner)["records"],0)

    def test_cooperating_writer_busy_never_advances_a06(self):
        ch=self.grant()
        fd=os.open(self.store.root,os.O_RDONLY|os.O_DIRECTORY)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            r=self.gate(ch)
            self.assertEqual((r.stage,r.reason),("A05","COOPERATING_WRITER_BUSY"))
            self.assertEqual(self.review.stats(self.owner)["records"],0)
        finally:
            os.close(fd)
        self.assertEqual(self.gate(ch).status,"REVIEWED")

    def test_selected_missing_no_assessment_or_orphan_cleanup(self):
        env=self.store.get_observation(self.obs)
        (self.store.root/env["evidence"]["payload_ref_str"]).unlink()
        self.assertEqual(self.gate(self.grant()).stage,"A04")
        inventory=audit_inventory(self.store.root)
        self.assertEqual(inventory.status,"COMPLETE_CANDIDATE_CENSUS")
        self.assertEqual(inventory.missing_payload_count,1)
        self.assertFalse(inventory.deletion_allowed)
        self.assertEqual(self.review.stats(self.owner)["records"],0)

    def test_a05_wrong_checkpoint_cannot_poison_replay_ledger(self):
        ch=self.grant()
        self.assertEqual(self.gate(ch,expected_checkpoint_sha256="0"*64).stage,"A05")
        self.assertEqual(self.review.stats(self.owner)["records"],0)
        self.assertEqual(self.gate(ch).status,"REVIEWED")

    def test_generalized_imu_profile_separate_synthetic_rehearsal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/"spool";folder.mkdir(mode=0o700)
            scope=scope_fixture(GENERALIZED)
            row=row_fixture(scope,1,1_000_000_000)
            path=folder/scope.filename;raw=canonical_json(row)+b"\n"
            path.write_bytes(raw);path.chmod(0o600)
            completed={"state":"COMPLETED","filename":scope.filename,"written":1,
                "enqueued":1,"written_bytes":len(raw),"history_committed":False,"actuation_enabled":False}
            p=preview_spool(folder,scope,completed)
            self.assertEqual(p.status,"PREVIEW")
            store=EvidenceStore(root/"store")
            self.assertEqual(apply_spool(store,folder,scope,completed,
                expected_spool_sha256=p.spool_sha256).status,"IMPORTED")
            obs,=(p.stem for p in store.observations.glob("obs_*.json"))
            cp=verify_selected(store.root,obs)
            owner=object();reader=LocalEvidenceReader(store.root,owner=owner)
            reader.register_evidence(owner,canonical_json(verified_ref_from_store(store,obs)),
                 purposes=frozenset({"diagnostics"}),retention_seconds=60,
                 metadata_consent=True,payload_consent=True)
            ch=reader.grant(owner,obs,purpose="diagnostics",payload=True,ttl_seconds=30)
            review=TemporalReview(owner=owner,
                clock=HostClock("synthetic-host","synthetic-domain","synthetic-boot"))
            r=pilot_review.review_record(reader,review,owner,ch,obs,
                expected_checkpoint_sha256=cp.checkpoint.sha256)
            self.assertEqual(r.status,"REVIEWED",r)
            self.assertFalse(r.live_delivery)

if __name__=="__main__":
    unittest.main()
