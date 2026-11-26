"""Use the pinned public Console owner fixture and real correlation helper.

The fixture is synthetic; adaptation supplies the documented source-owner
producer label and completed-spool metadata, NOT private producer execution.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest

from reality_ingress.bounded_intake import SourceScope, preview_spool, apply_spool
from reality_ingress.evidence import EvidenceStore
from reality_ingress.generic import canonical_json
from reality_ingress.consumer_ref import verified_ref_from_store
from reality_ingress.session_binding import SuppliedEvidence, resolve_session

CONSOLE = Path(os.environ["CONSOLE_OWNER_CHECKOUT"])
sys.path.insert(0, str(CONSOLE / "scripts/tests"))
import test_ri_periph_compat as console_owner


class OwnerIntakeTests(unittest.TestCase):
    def test_intake_preserves_actual_console_helper_compatibility(self):
        console, row = console_owner.fixtures()
        producer = "paky-01/imu_publish.py:IMU-RI-01-candidate"
        row["producer_str"] = producer
        row["temporal_binding"]["receive_timestamp_method"] = "userspace_after_existing_WIT_serial_read"
        original = row["payload"]["console_ingest_sample"]
        scope = SourceScope(producer, original["robot_id"], original["sensor_id"],
            original["source_id"], original["sensor_frame_id"], original["session_id"],
            row["temporal_binding"]["clock_domain_ref"]["boot_id_str"])
        raw = canonical_json(row)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            spool.mkdir(mode=0o700)
            path = spool / scope.filename
            path.write_bytes(raw+b"\n")
            path.chmod(0o600)
            completed = {"state":"COMPLETED", "filename":scope.filename,
                         "written":1,"enqueued":1,"history_committed":False,
                         "actuation_enabled":False}
            preview = preview_spool(spool,scope,completed)
            self.assertEqual(preview.status,"PREVIEW",preview)
            store = EvidenceStore(root/"store")
            applied = apply_spool(store,spool,scope,completed,
                                  expected_spool_sha256=preview.spool_sha256)
            self.assertEqual(applied.status,"IMPORTED",applied)
            self.assertEqual(store.verify()["status"],"PASS")
            obs_path, = store.observations.glob("*.json")
            env = store.get_observation(obs_path.stem)
            ref = verified_ref_from_store(store,obs_path.stem)
            saved = (store.root/env["evidence"]["payload_ref_str"]).read_bytes()
            self.assertEqual(saved,raw)
            self.assertTrue(console_owner.correlate(console,ref,saved)["matched"])
            self.assertFalse(console_owner.correlate(console,ref,saved)["console_boot_verified"])
            resolved = resolve_session(SuppliedEvidence(canonical_json(ref),canonical_json(env),saved))
            self.assertEqual(resolved.status,"CONTENT_MATCHED")
            self.assertEqual(resolved.binding.key.session_id,scope.session_id)
            self.assertFalse(ref["source_verified"])
            self.assertFalse(resolved.reference_issuance_verified)


if __name__ == "__main__":
    unittest.main()
