"""Opt-in owner-local synthetic producer rehearsal, never public CI.

Requires an explicit clean pinned private producer checkout. Imports its
existing synthetic test helpers only. No serial/HTTP or actual robot data.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from reality_ingress.bounded_intake import SourceScope,preview_spool,apply_spool
from reality_ingress.evidence import EvidenceStore
from reality_ingress.consumer_ref import verified_ref_from_store
from reality_ingress.evidence_access import LocalEvidenceReader
from reality_ingress.integrity_inspection import verify_selected
from reality_ingress.generic import canonical_json
from reality_ingress.temporal_review import HostClock,TemporalReview
from scripts.pilot_review import review_record

PINS={
    "paky":("ca5fd652d43cdf5298ddf50470c98e0724ac5b5f",
            {"scripts/imu_ri_export.py":"495255dbd72de4cbb672f34568807a90a17b0153",
             "tests/test_imu_ri_export.py":"ff6604d75d3ac6bd76c7ce9164bfbebc3aff8e6e"}),
    "imu":("b8fd0b714098780792c9e16aa1b00ac3d583b037",
           {"src/rgd_imu/ri_export.py":"8d73c81bd11bcf19395f26ba15ec722f83337f63",
            "tests/test_ri_export.py":"218526fa77c08731e52b54b2204d7b97639afc96"}),
}

class PrivateOwnerRehearsal(unittest.TestCase):
    def test_actual_private_exporter_to_full_ri_review(self):
        kind=os.environ.get("PILOT_PRODUCER_KIND")
        self.assertIn(kind,PINS,"Select an explicit approved producer checkout")
        root=Path(os.environ["PILOT_PRODUCER_CHECKOUT"]).resolve(strict=True)
        commit,blobs=PINS[kind]
        def git(*args):
            return subprocess.check_output(["git","-C",str(root),*args],
                                           timeout=20).decode().strip()
        self.assertEqual(git("rev-parse","HEAD"),commit)
        self.assertEqual(git("status","--porcelain","--untracked-files=all"),"",
                         "Use a clean isolated source checkout")
        for path,sha in blobs.items():
            self.assertEqual(git("hash-object",path),sha)
        sys.path.insert(0,str(root/"tests"))
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);folder=tmp/"spool";folder.mkdir(mode=0o700)
            if kind=="paky":
                import test_imu_ri_export as fixture
                boot="bc7e69f1-4482-4bfc-8bf9-615f56cf31b0"
                domain={"clock_domain_id_str":"chronos.monotonic.boot:"+boot,
                    "layer_enum_str":"CHRONOS","clock_kind_enum_str":"MONOTONIC",
                    "epoch_ref_str":"linux-boot:"+boot,"timescale_enum_str":"MONOTONIC",
                    "boot_id_str":boot}
                with patch.object(fixture.bridge,"clock_domain",return_value=domain):
                    ex=fixture.bridge.RiExport(folder,"a"*32)
                    for seq,mono in ((1,1_000_000_000),(2,2_000_000_000)):
                        ex.offer(fixture.sample(seq,mono),fixture.pair(mono))
                    report=ex.close()
            else:
                sys.path.insert(0,str(root/"src"))
                import test_ri_export as fixture
                ex=fixture.make_export(folder)
                ex.offer(*fixture.source_sample(1,1_000_000_000))
                ex.offer(*fixture.source_sample(2,2_000_000_000))
                report=ex.close()
            self.assertEqual(report["state"],"COMPLETED")
            self.assertEqual(report["written"],2)
            self.assertRegex(report["filename"],r"^imu-[0-9a-f]{32}\.jsonl$")
            raw=(folder/report["filename"]).read_bytes()
            row=json.loads(raw.splitlines()[0]);s=row["payload"]["console_ingest_sample"]
            # Synthetic fixture labels only. The physical pilot must configure
            # scope independently from the spool under operator review.
            scope=SourceScope(row["producer_str"],s["robot_id"],s["sensor_id"],
                s["source_id"],s["sensor_frame_id"],s["session_id"],
                row["temporal_binding"]["clock_domain_ref"]["boot_id_str"])
            p=preview_spool(folder,scope,report)
            self.assertEqual(p.status,"PREVIEW",p)
            store=EvidenceStore(tmp/"store")
            applied=apply_spool(store,folder,scope,report,expected_spool_sha256=p.spool_sha256)
            self.assertEqual((applied.status,applied.created),("IMPORTED",2))
            repeat=apply_spool(store,folder,scope,report,expected_spool_sha256=p.spool_sha256)
            self.assertEqual((repeat.created,repeat.already_present),(0,2))
            self.assertEqual(store.verify()["status"],"PASS")
            owner=object();reader=LocalEvidenceReader(store.root,owner=owner)
            temporal=TemporalReview(owner=owner,clock=HostClock("synthetic-host","synthetic-domain","synthetic-boot"))
            obs=tuple(p.stem for p in store.observations.glob("obs_*.json"))
            self.assertEqual(len(obs),2)
            for item in obs:
                proof=verify_selected(store.root,item)
                self.assertEqual(proof.status,"CHECKED")
                reader.register_evidence(owner,canonical_json(verified_ref_from_store(store,item)),
                    purposes=frozenset({"diagnostics"}),retention_seconds=60,
                    metadata_consent=True,payload_consent=True)
                ch=reader.grant(owner,item,purpose="diagnostics",payload=True,ttl_seconds=30,max_reads=2)
                result=review_record(reader,temporal,owner,ch,item,
                                     expected_checkpoint_sha256=proof.checkpoint.sha256)
                self.assertEqual(result.status,"REVIEWED")
                self.assertEqual(result.receipt_age_state,"UNKNOWN")
                self.assertFalse(result.live_delivery)
                repeat=review_record(reader,temporal,owner,ch,item,presentation="REPLAY",
                                     expected_checkpoint_sha256=proof.checkpoint.sha256)
                self.assertEqual(repeat.status,"DUPLICATE")
            self.assertEqual(temporal.stats(owner)["records"],2)

if __name__=="__main__":
    unittest.main()
