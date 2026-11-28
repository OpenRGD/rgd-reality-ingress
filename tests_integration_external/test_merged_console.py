"""Cross-owner stack rehearsal against actual merged Console helper."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from reality_ingress.bounded_intake import SourceScope,preview_spool,apply_spool
from reality_ingress.evidence import EvidenceStore
from reality_ingress.evidence_access import LocalEvidenceReader
from reality_ingress.consumer_ref import verified_ref_from_store
from reality_ingress.integrity_inspection import verify_selected
from reality_ingress.generic import canonical_json
from reality_ingress.temporal_review import HostClock,TemporalReview
from scripts.pilot_review import review_record

CONSOLE=Path(os.environ["CONSOLE_OWNER_CHECKOUT"])
sys.path.insert(0,str(CONSOLE/"scripts/tests"))
import test_ri_periph_compat as console_owner

class MergedConsoleRehearsal(unittest.TestCase):
    def test_publisher_shape_to_merged_console_and_a06(self):
        console,row=console_owner.fixtures()
        row["producer_str"]="paky-01/imu_publish.py:IMU-RI-01-candidate"
        row["temporal_binding"]["receive_timestamp_method"]="userspace_after_existing_WIT_serial_read"
        s=row["payload"]["console_ingest_sample"]
        scope=SourceScope(row["producer_str"],s["robot_id"],s["sensor_id"],s["source_id"],
            s["sensor_frame_id"],s["session_id"],row["temporal_binding"]["clock_domain_ref"]["boot_id_str"])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/"spool";folder.mkdir(mode=0o700)
            raw=canonical_json(row);path=folder/scope.filename
            path.write_bytes(raw+b"\n");path.chmod(0o600)
            report={"state":"COMPLETED","filename":scope.filename,"written":1,"enqueued":1,
                "history_committed":False,"actuation_enabled":False}
            p=preview_spool(folder,scope,report);self.assertEqual(p.status,"PREVIEW")
            store=EvidenceStore(root/"store")
            self.assertEqual(apply_spool(store,folder,scope,report,
                expected_spool_sha256=p.spool_sha256).status,"IMPORTED")
            obs,=(p.stem for p in store.observations.glob("obs_*.json"))
            proof=verify_selected(store.root,obs);self.assertEqual(proof.status,"CHECKED")
            owner=object();reader=LocalEvidenceReader(store.root,owner=owner)
            reader.register_evidence(owner,canonical_json(verified_ref_from_store(store,obs)),
                 purposes=frozenset({"diagnostics"}),retention_seconds=60,
                 metadata_consent=True,payload_consent=True)
            ch=reader.grant(owner,obs,purpose="diagnostics",payload=True,ttl_seconds=30,max_reads=3)
            view=reader.read(ch,obs,purpose="diagnostics",include_payload=True)
            self.assertEqual(view.status,"PAYLOAD_RESOLVED")
            self.assertEqual(view.payload_bytes,raw)
            correlation=console_owner.correlate(console,json.loads(view.reference_json),view.payload_bytes)
            self.assertTrue(correlation["matched"]);self.assertFalse(correlation["console_boot_verified"])
            self.assertFalse(correlation["source_verified"])
            review=TemporalReview(owner=owner,clock=HostClock("synthetic-host","synthetic-domain","synthetic-boot"))
            result=review_record(reader,review,owner,ch,obs,
                                 expected_checkpoint_sha256=proof.checkpoint.sha256)
            self.assertEqual(result.status,"REVIEWED",result)
            self.assertFalse(result.live_delivery)
            self.assertEqual(result.receipt_age_state,"UNKNOWN")

if __name__=="__main__":
    unittest.main()
