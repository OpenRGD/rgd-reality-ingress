"""Use exact public owner fixtures; never read a sensor or real evidence."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

from reality_ingress.consumer_ref import verified_ref_from_store
from reality_ingress.evidence import EvidenceStore
from reality_ingress.generic import canonical_json, record_sample
from reality_ingress.session_binding import SuppliedEvidence, resolve_session

CONSOLE_OWNER = Path(os.environ["CONSOLE_OWNER_CHECKOUT"])
COG_OWNER = Path(os.environ["COG_OWNER_CHECKOUT"])
sys.path.insert(0, str(CONSOLE_OWNER / "scripts/tests"))
sys.path.insert(0, str(COG_OWNER / "tests_ri02"))
import test_ri_periph_compat as console_owner
import test_imu_evidence_binding as cog_owner


class OwnerProfileTests(unittest.TestCase):
    def test_actual_console_owner_fixture_and_new_resolver_agree(self):
        sample, row = console_owner.fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "store")
            env, _ = record_sample(store, row)
            ref = verified_ref_from_store(store, env["observation_id_str"])
            raw = canonical_json(row)
            result = resolve_session(SuppliedEvidence(canonical_json(ref), canonical_json(env), raw))
            self.assertEqual(result.status, "CONTENT_MATCHED")
            self.assertEqual(result.binding.key.session_id, sample["session_id"])
            self.assertEqual(result.binding.key.sequence, sample["sequence"])
            self.assertTrue(console_owner.correlate(sample, ref, raw)["matched"])
            self.assertFalse(result.binding.source_verified)
            self.assertEqual(result.binding.clock_relation, "NOT_ESTABLISHED")
            # No schema repin or false clock claim.
            self.assertNotIn("session_id", ref)
            self.assertFalse(console_owner.correlate(sample, ref, raw)["console_boot_verified"])

    def test_actual_cog_owner_proposed_profile_stays_unresolved_in_ri(self):
        fixture = cog_owner.BindingTests(
            methodName="test_actual_RI_generic_payload_corresponds_to_exact_console_record")
        fixture.setUp()
        try:
            ref, raw = fixture.ref, fixture.raw
            env = fixture.store.get_observation(ref["observation_id"])
            result = resolve_session(SuppliedEvidence(canonical_json(ref), canonical_json(env), raw))
            self.assertEqual(result.reason, "CONSOLE_COPY_PROFILE_REVIEW_PENDING")
            self.assertIsNone(result.binding)
            # Preserve the owner's independent proposed-profile behavior.
            self.assertEqual(fixture.accept()["status"], "CONTENT_MATCHED")
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
