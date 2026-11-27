"""Actual COG consumer boundary, with synthetic original IMU stored data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from reality_ingress.evidence import EvidenceStore
from reality_ingress.generic import record_sample, canonical_json
from reality_ingress.consumer_ref import verified_ref_from_store
from reality_ingress.evidence_access import LocalEvidenceReader
from reality_ingress.temporal_review import HostClock, PublisherClockClaim, TemporalReview
from rgd_cognition.ri_observation_ref import (
    RIReferenceContract, RIReferenceConsumer, RIHostPolicy, RILocalOwners, RIRefError,
)

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tests_intake"))
from test_bounded_intake import scope_fixture,row_fixture

class CogBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=EvidenceStore(Path(self.tmp.name)/"store")
        self.scope=scope_fixture()
        env,_=record_sample(self.store,row_fixture(self.scope,7,3_900_000_000))
        self.obs=env["observation_id_str"]
        self.ref=verified_ref_from_store(self.store,self.obs)
        self.owner=object()
        self.reader=LocalEvidenceReader(self.store.root,owner=self.owner)
        self.reader.register_evidence(self.owner,canonical_json(self.ref),
            purposes=frozenset({"cognition"}),retention_seconds=120,
            metadata_consent=True,payload_consent=True)
        self.clock=HostClock("synthetic-host",self.ref["time"]["clock_domain_id"],
                             self.ref["time"]["boot_id"])
        self.claim=PublisherClockClaim(self.clock,self.scope.source_id,"imu",
                                       self.scope.frame_id,self.scope.session_id)
        self.review=TemporalReview(owner=self.owner,clock=self.clock,clock_ns=lambda:4_000_000_000)

    def view(self,payload):
        ch=self.reader.grant(self.owner,self.obs,purpose="cognition",ttl_seconds=30,payload=payload)
        return self.reader.read(ch,self.obs,purpose="cognition",include_payload=payload)

    def cog(self,assert_clock):
        ref=self.ref;owners=RILocalOwners()
        policy=RIHostPolicy(local_alias="synthetic-robot",allowed_source_id=ref["source_id"],
            allowed_modality=ref["modality"],allowed_frame_id=ref["reference_frame_id"],
            clock_domain_id=ref["time"]["clock_domain_id"],boot_id=ref["time"]["boot_id"],
            same_boot_clock_trusted=assert_clock,metadata_access=True,consent=True,payload_access=True)
        schema=RIReferenceContract((ROOT/"contracts/consumer-observation-ref.v0.1-candidate.schema.json").read_bytes())
        return RIReferenceConsumer(schema,policy=policy,owners=owners,clock_ns=lambda:4_000_000_000),owners.reader

    def test_actual_cog_historical_view_remains_unknown_when_not_promoted(self):
        view=self.view(True)
        assessment=self.review.assess(self.owner,view,presentation="REIMPORT",publisher_clock=self.claim)
        self.assertEqual(assessment.status,"ASSESSED",assessment)
        sidecar=json.loads(assessment.assessment_json)
        self.assertEqual(sidecar["receipt_age_state"],"RECENT_RECEIPT")
        self.assertFalse(sidecar["live_delivery"])
        self.assertEqual(sidecar["source_measurement_freshness"],"UNKNOWN")
        consumer,ch=self.cog(False)
        result=consumer.accept(ch,json.loads(view.reference_json),evidence_state=view.availability,
                               payload_bytes=view.payload_bytes)
        self.assertEqual(result["status"],"ACCEPTED_REFERENCE")
        self.assertEqual(result["notice"]["freshness"],"UNKNOWN")
        self.assertFalse(result["notice"]["can_generate_goal"])
        self.assertFalse(result["notice"]["may_actuate"])

    def test_actual_cog_legacy_same_boot_setting_can_label_archive_recent(self):
        view=self.view(True)
        assessment=self.review.assess(self.owner,view,presentation="REPLAY",publisher_clock=self.claim)
        record=json.loads(assessment.assessment_json)
        consumer,ch=self.cog(True)
        result=consumer.accept(ch,json.loads(view.reference_json),evidence_state="AVAILABLE",
                               payload_bytes=view.payload_bytes)
        # Characterization, NOT permission to configure archive reads this way.
        self.assertEqual(result["notice"]["freshness"],"FRESH")
        self.assertFalse(record["live_delivery"])
        self.assertEqual(record["source_measurement_freshness"],"UNKNOWN")
        self.assertFalse(result["notice"]["can_generate_goal"])

    def test_a06_report_is_not_a_reference_or_cog_update(self):
        meta=self.view(False);checked=self.view(True)
        first=self.review.assess(self.owner,meta)
        self.assertEqual(first.status,"ASSESSED")
        consumer,ch=self.cog(False)
        consumer.accept(ch,json.loads(meta.reference_json),evidence_state="UNKNOWN")
        with self.assertRaises(RIRefError):
            consumer.accept(ch,json.loads(first.assessment_json),evidence_state="UNKNOWN")
        duplicate=self.review.assess(self.owner,checked,presentation="REPLAY",publisher_clock=self.claim)
        self.assertEqual(duplicate.status,"DUPLICATE")
        self.assertIsNone(duplicate.assessment_json)
        with self.assertRaisesRegex(RIRefError,"OBSERVATION_ID_COLLISION"):
            consumer.accept(ch,json.loads(checked.reference_json),evidence_state="AVAILABLE",
                            payload_bytes=checked.payload_bytes)

if __name__=="__main__":
    unittest.main()
