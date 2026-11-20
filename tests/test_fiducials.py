import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from reality_ingress.evidence import EvidenceStore, IntegrityError
from reality_ingress.fiducials import FiducialStore, load_calibration, trajectories, make_markers, offline_scan
from reality_ingress.timebase import receive_stamp
from reality_ingress.calibration import make_checkerboard


class FiducialAgnosticContractTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.store = EvidenceStore(self.work.name)

    def test_generic_fiducial_record_no_self_or_robot(self):
        o = self.store.record(data=b'fixture', source_id='camera.any', modality='rgb',
             reference_frame_id='ref.camera.any', sequence=1,
             timestamp=receive_stamp(), media_type='image/jpeg', representation={})
        m = [{'marker_id_uint': 11, 'corners_xy_normalized_arr':
              [[0.1,0.1],[0.2,0.1],[0.2,0.2],[0.1,0.2]],
              'center_xy_normalized_arr':[0.15,0.15],
              'perimeter_px_float':100.0,'pose_camera':None}]
        fid = FiducialStore(self.store)
        fid.record(observation_id=o['observation_id_str'], markers=m,
                   processor={'processing_signature_sha256_hex_str':'f'*64})
        raw = next(fid.root.glob('fid_*.json')).read_text()
        self.assertNotIn('"self"', raw.lower())
        self.assertNotIn('"robot_id"', raw.lower())
        self.assertEqual(self.store.verify()['status'], 'PASS')
        self.assertEqual(self.store.verify()['fiducial_derivation_count'], 1)
        p=next(fid.root.glob('fid_*.json'))
        p.write_text(raw.replace('\"marker_id_uint\": 11', '\"marker_id_uint\": 12'))
        self.assertEqual(self.store.verify()['status'], 'FAIL')
        self.assertIn('Fiducial derivation integrity mismatch', str(self.store.verify()['errors']))

    def test_checkerboard_print_size(self):
        p = Path(self.work.name)/'board.svg'
        make_checkerboard(p, columns=9, rows=6, square_mm=18)
        s=p.read_text()
        self.assertIn('width="200mm"',s)
        self.assertIn('height="146mm"',s)


@unittest.skipUnless(importlib.util.find_spec('cv2') and importlib.util.find_spec('numpy'), 'OpenCV and numpy optional')
class FiducialVisionTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        self.cv2 = cv2
        self.np = np
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.store = EvidenceStore(self.work.name)

    def record_marker(self, mid, x, seq):
        marker = self.cv2.aruco.generateImageMarker(self.cv2.aruco.getPredefinedDictionary(self.cv2.aruco.DICT_4X4_50), mid, 160)
        image = self.np.full((480, 640, 3), 255, dtype=self.np.uint8)
        image[140:300, x:x+160] = self.cv2.cvtColor(marker, self.cv2.COLOR_GRAY2BGR)
        ok, j = self.cv2.imencode('.jpg', image)
        self.assertTrue(ok)
        return self.store.record(data=j.tobytes(), source_id='camera.xyz', modality='rgb',
              reference_frame_id='frame.camera.xyz', sequence=seq, timestamp=receive_stamp(),
              media_type='image/jpeg', representation={'width_uint':640,'height_uint':480})

    def test_detect_track_idempotency_and_no_3d_without_calibration(self):
        o1 = self.record_marker(11, 150, 1)
        o2 = self.record_marker(11, 210, 2)
        originals = [(self.store.observations/(o['observation_id_str']+'.json')).read_bytes() for o in (o1, o2)]
        result1 = offline_scan(self.work.name, limit=2)
        result2 = offline_scan(self.work.name, limit=2)
        self.assertEqual(result1['processed'], 2)
        self.assertEqual(result1['markers_detected_total'], 2)
        self.assertEqual(result2['already_derived'], 2)
        self.assertEqual(self.store.verify()['status'], 'PASS')
        tracks=trajectories(self.work.name)
        self.assertEqual([r['marker_id'] for r in tracks],[11,11])
        self.assertIsNone(tracks[0]['pose_camera'])
        self.assertIsNone(tracks[1]['pose_camera'])
        self.assertAlmostEqual(tracks[1]['delta_xy_normalized'][0], 60/640,places=3)
        for i, o in enumerate((o1,o2)):
            self.assertEqual((self.store.observations/(o['observation_id_str']+'.json')).read_bytes(), originals[i])

    def test_camera_relative_3d_pose_with_explicit_calibration(self):
        self.record_marker(12, 240, 1)
        p=Path(self.work.name)/'camera-intrinsics.json'
        p.write_text(json.dumps({'camera_matrix': [[800,0,320],[0,800,240],[0,0,1]],
                  'distortion_coefficients': [0,0,0,0,0], 'width':640, 'height':480}))
        r=offline_scan(self.work.name, limit=1,marker_size_m=0.04,calibration_path=p)
        self.assertEqual(r['markers_detected_total'],1)
        one=json.loads(next((self.store.root/'fiducials').glob('fid_*.json')).read_text())
        pose=one['interpretation']['markers'][0]['pose_camera']
        self.assertIsNotNone(pose)
        self.assertGreater(pose['position_xyz_m_arr'][2],0.05)
        self.assertEqual(pose['reference_frame_str'],'camera_optical')
        self.assertEqual(self.store.verify()['status'],'PASS')

    def test_generate_marker_png(self):
        p=Path(self.work.name)/'markers'
        paths=make_markers(p, [11,12,13], 'DICT_4X4_50')
        self.assertEqual(len(paths),3)
        self.assertTrue(all(Path(x['png']).is_file() and Path(x['print_actual_size_svg']).is_file() for x in paths))


if __name__ == '__main__':
    unittest.main()
