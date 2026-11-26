"""Real pinned Console and COG consumers; all source data synthetic."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from reality_ingress.evidence import EvidenceStore
from reality_ingress.generic import canonical_json, record_sample
from reality_ingress.consumer_ref import verified_ref_from_store
from reality_ingress.evidence_access import LocalEvidenceReader
from rgd_cognition.ri_observation_ref import (
    RIReferenceContract, RIReferenceConsumer, RIHostPolicy, RILocalOwners, RIRefError,
)

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = Path(os.environ["CONSOLE_OWNER_CHECKOUT"])
sys.path.insert(0, str(CONSOLE/"scripts/tests"))
import test_ri_periph_compat as console_owner


class ConsumerAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = EvidenceStore(Path(self.tmp.name)/"store")
        self.console, row = console_owner.fixtures()
        # Actual owner's synthetic fixture with documented producer profile
        # metadata. Not execution of private publisher or physical hardware.
        row["producer_str"]="paky-01/imu_publish.py:IMU-RI-01-candidate"
        row["temporal_binding"]["receive_timestamp_method"]="userspace_after_existing_WIT_serial_read"
        self.env,_=record_sample(self.store,row)
        self.obs=self.env["observation_id_str"]
        self.original=verified_ref_from_store(self.store,self.obs)
        self.owner=object()
        self.reader=LocalEvidenceReader(self.store.root,owner=self.owner)
        self.reader.register_evidence(self.owner,canonical_json(self.original),
            purposes=frozenset({"diagnostics","cognition"}),retention_seconds=120,
            metadata_consent=True,payload_consent=True)

    def get(self, purpose, payload):
        ch=self.reader.grant(self.owner,self.obs,purpose=purpose,ttl_seconds=30,payload=payload)
        return self.reader.read(ch,self.obs,purpose=purpose,include_payload=payload)

    def cog(self, payload):
        ref=self.original
        owners=RILocalOwners()
        policy=RIHostPolicy(local_alias="synthetic-robot",allowed_source_id=ref["source_id"],
            allowed_modality=ref["modality"],allowed_frame_id=ref["reference_frame_id"],
            clock_domain_id=ref["time"]["clock_domain_id"],boot_id=ref["time"]["boot_id"],
            same_boot_clock_trusted=False,metadata_access=True,consent=True,payload_access=payload)
        contract=RIReferenceContract((ROOT/"contracts/consumer-observation-ref.v0.1-candidate.schema.json").read_bytes())
        return RIReferenceConsumer(contract,policy=policy,owners=owners),owners.reader

    def test_console_exact_payload_and_legacy_ref(self):
        r=self.get("diagnostics",True)
        self.assertEqual(r.status,"PAYLOAD_RESOLVED")
        ref=json.loads(r.reference_json)
        self.assertEqual(ref,self.original)
        match=console_owner.correlate(self.console,ref,r.payload_bytes)
        self.assertTrue(match["matched"],match)
        self.assertFalse(match["console_boot_verified"])
        self.assertFalse(match["source_verified"])

    def test_cog_metadata_unknown_no_payload_no_goal(self):
        r=self.get("cognition",False)
        consumer,ch=self.cog(False)
        result=consumer.accept(ch,json.loads(r.reference_json),evidence_state=r.availability)
        self.assertEqual(result["status"],"ACCEPTED_REFERENCE")
        n=result["notice"]
        self.assertEqual(n["evidence_state"],"UNKNOWN")
        self.assertFalse(n["payload_checked_at_cog"])
        self.assertFalse(n["can_generate_goal"])
        self.assertEqual(n["freshness"],"UNKNOWN")

    def test_cog_payload_scope_checked_no_authority(self):
        r=self.get("cognition",True)
        consumer,ch=self.cog(True)
        result=consumer.accept(ch,json.loads(r.reference_json),
            evidence_state=r.availability,payload_bytes=r.payload_bytes)
        self.assertEqual(result["status"],"ACCEPTED_REFERENCE")
        n=result["notice"]
        self.assertTrue(n["payload_checked_at_cog"])
        self.assertFalse(n["grants_authority"])
        self.assertFalse(n["may_actuate"])
        self.assertIsNone(n["life_id"])

    def test_cog_same_reference_fingerprint_requires_owner_review_for_upgrade(self):
        metadata=self.get("cognition",False)
        payload=self.get("cognition",True)
        consumer,ch=self.cog(True)
        consumer.accept(ch,json.loads(metadata.reference_json),evidence_state="UNKNOWN")
        # Existing owner semantics are preserved, not bypassed. A local
        # metadata projection and checked-payload projection differ in the
        # integrity flag, so don't silently upgrade an already consumed ref.
        with self.assertRaisesRegex(RIRefError,"OBSERVATION_ID_COLLISION"):
            consumer.accept(ch,json.loads(payload.reference_json),
                evidence_state="AVAILABLE",payload_bytes=payload.payload_bytes)

if __name__=="__main__":
    unittest.main()
