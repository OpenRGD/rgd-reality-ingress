"""Agnostic fiducial perception over immutable visual evidence.

This is a NON-NORMATIVE peripheral processor. A tag ID labels a visual
fiducial, NOT an agent, a robot part, or SELF. Camera-frame pose requires
calibrated intrinsics and a measured printed marker size; without these we
only report image-plane positions. No motor IO or Chronograf claims.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .derivations import canonical_bytes, sha256
from .evidence import EvidenceStore, IntegrityError, _atomic_create
from .timebase import derivation_stamp

SCHEMA_REF = 'urn:openrgd:experimental:reality-ingress:fiducial-derivation:v0'
FIDUCIAL_ID_RE = re.compile(r'^fid_[0-9a-f]{64}$')


def load_cv():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError('Install OpenCV inside the perception environment') from exc
    if not hasattr(cv2, 'aruco'):
        raise RuntimeError('This OpenCV build lacks cv2.aruco; install an ArUco-capable OpenCV build in a dedicated environment')
    return cv2


def dictionary(cv2, name: str):
    if name not in ('DICT_4X4_50', 'DICT_APRILTAG_36h11', 'DICT_5X5_100'):
        raise ValueError('Supported dictionaries: DICT_4X4_50, DICT_APRILTAG_36h11, DICT_5X5_100')
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name))


def detector(cv2, name: str):
    d = dictionary(cv2, name)
    if hasattr(cv2.aruco, 'ArucoDetector'):
        obj = cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters())
        return obj.detectMarkers
    return lambda frame: cv2.aruco.detectMarkers(frame, d)


def make_markers(path: str | Path, ids: list[int], dictionary_name: str, marker_pixels: int = 600, side_mm: float = 36.0):
    cv2 = load_cv()
    d = dictionary(cv2, dictionary_name)
    if marker_pixels < 160:
        raise ValueError('marker_pixels should be at least 160')
    if not 5 <= side_mm <= 150:
        raise ValueError('side_mm must be between 5 and 150')
    folder = Path(path).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for mid in ids:
        if mid < 0 or mid >= d.bytesList.shape[0]:
            raise ValueError(f'Marker id outside dictionary: {mid}')
        marker = cv2.aruco.generateImageMarker(d, mid, marker_pixels)
        # Add plain white quiet-zone border to improve detection.
        bordered = cv2.copyMakeBorder(marker, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
        target = folder / f'{dictionary_name}_id{mid}.png'
        if not cv2.imwrite(str(target), bordered):
            raise IOError(f'Could not write marker: {target}')
        # True-to-scale SVG. Black outer square (not quiet zone) is exactly
        # side_mm when printed at 100%, for calibrated pose estimation.
        tiles = d.markerSize + 2
        cell = side_mm / tiles
        margin = 5.0
        shapes = []
        for yy in range(tiles):
            for xx in range(tiles):
                pixel_y = min(marker_pixels-1, int((yy+0.5)*marker_pixels/tiles))
                pixel_x = min(marker_pixels-1, int((xx+0.5)*marker_pixels/tiles))
                if int(marker[pixel_y, pixel_x]) < 128:
                    shapes.append(f'<rect x="{margin + xx*cell:.5f}" y="{margin + yy*cell:.5f}" width="{cell:.5f}" height="{cell:.5f}"/>')
        full = side_mm + 2 * margin
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{full:.5f}mm" '
               f'height="{full+6:.5f}mm" viewBox="0 0 {full:.5f} {full+6:.5f}">'
               f'<rect width="{full:.5f}" height="{full+6:.5f}" fill="white"/>'
               f'<g fill="black">'+''.join(shapes)+'</g>'
               f'<text x="{full/2:.5f}" y="{full+3:.5f}" font-family="sans-serif" '
               f'font-size="3" text-anchor="middle" fill="black">ID {mid}</text></svg>')
        svg_target = folder / f'{dictionary_name}_id{mid}_{side_mm:g}mm.svg'
        svg_target.write_text(svg, encoding='utf-8')
        results.append({'id': mid, 'png': str(target), 'print_actual_size_svg': str(svg_target),
                        'black_square_side_mm': side_mm})
    return results


def load_calibration(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    p = Path(path).expanduser()
    doc = json.loads(p.read_text(encoding='utf-8'))
    k = doc['camera_matrix']
    dist = doc['distortion_coefficients']
    if len(k) != 3 or any(len(row) != 3 for row in k):
        raise ValueError('Calibration camera_matrix must be 3x3')
    if not isinstance(dist, list) or not dist:
        raise ValueError('Calibration distortion_coefficients must be a nonempty list')
    flat = [float(v) for row in k for v in row] + [float(x) for x in dist]
    if any(not math.isfinite(v) for v in flat) or flat[0] <= 0 or flat[4] <= 0:
        raise ValueError('Invalid calibration parameters')
    if not isinstance(doc.get('width'), int) or not isinstance(doc.get('height'), int):
        raise ValueError('Calibration must declare image width/height')
    return {'camera_matrix': k, 'distortion_coefficients': dist,
            'width': doc['width'], 'height': doc['height'],
            'calibration_sha256_hex_str': sha256(p.read_bytes())}


def detect(frame, *, dictionary_name='DICT_4X4_50', marker_size_m=None, calibration=None):
    """Pure perception, no event writes. Returns image-plane measurements.

    Calibrated pose is CAMERA-relative, not world- or robot-relative.
    """
    cv2 = load_cv()
    if (marker_size_m is None) != (calibration is None):
        raise ValueError('3D requires BOTH --marker-size-m and --calibration')
    if marker_size_m is not None and not (0.001 <= marker_size_m <= 1.0):
        raise ValueError('Marker side must be between 0.001 and 1 metre')
    h, w = frame.shape[:2]
    if calibration and (calibration['width'], calibration['height']) != (w, h):
        raise ValueError('Calibration image size does not match observations')
    corners, ids, _ = detector(cv2, dictionary_name)(frame)
    if ids is None:
        return []
    import numpy as np
    output = []
    for mid, pts0 in zip(ids.reshape(-1), corners):
        pts = np.asarray(pts0, dtype=np.float64).reshape(4, 2)
        center = pts.mean(axis=0)
        perimeter = sum(float(np.linalg.norm(pts[i] - pts[(i + 1) % 4])) for i in range(4))
        item = {
            'marker_id_uint': int(mid),
            'corners_xy_normalized_arr': [[round(float(x) / w, 7), round(float(y) / h, 7)] for x, y in pts],
            'center_xy_normalized_arr': [round(float(center[0]) / w, 7), round(float(center[1]) / h, 7)],
            'perimeter_px_float': round(perimeter, 3),
            'pose_camera': None,
        }
        if calibration is not None:
            half = marker_size_m / 2
            object_points = np.array([[-half, half, 0], [half, half, 0],
                                      [half, -half, 0], [-half, -half, 0]], dtype=np.float64)
            k = np.asarray(calibration['camera_matrix'], dtype=np.float64)
            distortion = np.asarray(calibration['distortion_coefficients'], dtype=np.float64)
            success, rvec, tvec = cv2.solvePnP(object_points, pts, k, distortion,
                                              flags=cv2.SOLVEPNP_IPPE_SQUARE)
            if success:
                projected, _ = cv2.projectPoints(object_points, rvec, tvec, k, distortion)
                error = float(np.sqrt(np.mean(np.sum((projected.reshape(4, 2) - pts) ** 2, axis=1))))
                if float(tvec[2, 0]) > 0 and math.isfinite(error):
                    item['pose_camera'] = {
                        'position_xyz_m_arr': [round(float(n), 7) for n in tvec.reshape(3)],
                        'rvec_xyz_rad_arr': [round(float(n), 7) for n in rvec.reshape(3)],
                        'reprojection_rmse_px_float': round(error, 4),
                        'reference_frame_str': 'camera_optical',
                        'method_str': 'calibrated_solvepnp_ippe_square',
                    }
        output.append(item)
    output.sort(key=lambda x: x['marker_id_uint'])
    return output


def check_markers(markers: list[dict[str, Any]]):
    seen = set()
    for marker in markers:
        mid = marker['marker_id_uint']
        if type(mid) is not int or mid < 0 or mid in seen:
            raise IntegrityError('Invalid or duplicate marker ID in one frame')
        seen.add(mid)
        for pt in marker['corners_xy_normalized_arr'] + [marker['center_xy_normalized_arr']]:
            if len(pt) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 or v > 1 for v in pt):
                raise IntegrityError('Marker coordinates must be finite normalized pairs')
        pose = marker['pose_camera']
        if pose is not None:
            if pose['reference_frame_str'] != 'camera_optical':
                raise IntegrityError('Invalid pose reference frame')
            for key in ('position_xyz_m_arr', 'rvec_xyz_rad_arr'):
                v = pose[key]
                if len(v) != 3 or any(not math.isfinite(x) for x in v):
                    raise IntegrityError('Invalid 3D pose')
            if pose['reprojection_rmse_px_float'] < 0:
                raise IntegrityError('Invalid reprojection error')


class FiducialStore:
    def __init__(self, store: EvidenceStore):
        self.store = store
        self.root = store.root / 'fiducials'
        self.root.mkdir(exist_ok=True, mode=0o700)

    def _path(self, fid_id):
        if not FIDUCIAL_ID_RE.fullmatch(fid_id):
            raise IntegrityError('Invalid fiducial derivation ID')
        return self.root / f'{fid_id}.json'

    def record(self, *, observation_id, markers, processor):
        check_markers(markers)
        observation = self.store.get_observation(observation_id)
        p = self.store.observations / f'{observation_id}.json'
        env_bytes = p.read_bytes()
        digest = observation['evidence']['payload_sha256_hex_str']
        content = self.store._payload_path(digest).read_bytes()
        if sha256(content) != digest:
            raise IntegrityError('Source frame payload changed')
        stamp = derivation_stamp()
        body = {
            'schema_ref_str': SCHEMA_REF,
            'normative_bool': False,
            'derived_from': {
                'observation_id_str': observation_id,
                'observation_envelope_sha256_hex_str': sha256(env_bytes),
                'payload_sha256_hex_str': digest,
            },
            'camera_reference_frame_id_str': observation['source']['reference_frame_id_str'],
            'frame_received_monotonic_ns': observation['temporal_binding']['received_monotonic_ns'],
            'temporal_binding': {
                **stamp,
                'chronograf_alignment_status_str': 'NOT_RESOLVED_BY_CHRONOGRAF',
                'capture_time_status_str': observation['temporal_binding'].get('source_time_status_str', 'UNKNOWN'),
            },
            'processor': processor,
            'interpretation': {
                'kind_str': 'visual_fiducial_landmarks',
                'markers': markers,
            },
            'provenance': {
                'producer_str': 'reality-ingress-python/0.3.0',
                'method_str': 'fiducials_derived_from_immutable_jpeg',
                'attestation_str': 'none',
            },
        }
        identifier = 'fid_' + sha256(canonical_bytes(body))
        if not _atomic_create(self._path(identifier), json.dumps(
                {'fiducial_derivation_id_str': identifier, **body},
                indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n'):
            raise IntegrityError('Fiducial derivation already exists')
        return identifier

    def find_existing(self, obs_id, signature):
        for f in self.root.glob('fid_*.json'):
            try:
                item = json.loads(f.read_text(encoding='utf-8'))
                if (item['derived_from']['observation_id_str'] == obs_id and
                        item['processor']['processing_signature_sha256_hex_str'] == signature):
                    return True
            except (ValueError, OSError, KeyError):
                continue
        return False

    def verify(self):
        errors = []
        refs = set()
        for f in sorted(self.root.glob('fid_*.json')):
            try:
                body = json.loads(f.read_text(encoding='utf-8'))
                fid_id = body.pop('fiducial_derivation_id_str')
                if not FIDUCIAL_ID_RE.fullmatch(fid_id) or f.name != f'{fid_id}.json':
                    raise IntegrityError('Fiducial derivation ID mismatch')
                if sha256(canonical_bytes(body)) != fid_id[4:]:
                    raise IntegrityError('Fiducial derivation integrity mismatch')
                if body['schema_ref_str'] != SCHEMA_REF:
                    raise IntegrityError('Unexpected fiducial schema')
                src = body['derived_from']
                obs_id = src['observation_id_str']
                env = self.store.get_observation(obs_id)
                source_path = self.store.observations / f'{obs_id}.json'
                if sha256(source_path.read_bytes()) != src['observation_envelope_sha256_hex_str']:
                    raise IntegrityError('Source envelope changed')
                if env['evidence']['payload_sha256_hex_str'] != src['payload_sha256_hex_str']:
                    raise IntegrityError('Source payload reference changed')
                actual = self.store._payload_path(src['payload_sha256_hex_str']).read_bytes()
                if sha256(actual) != src['payload_sha256_hex_str']:
                    raise IntegrityError('Source payload bytes changed')
                check_markers(body['interpretation']['markers'])
                refs.add(obs_id)
            except (ValueError, OSError, KeyError, IntegrityError, TypeError) as exc:
                errors.append({'filename': f.name, 'error': str(exc)})
        return {
            'status': 'FAIL' if errors else 'PASS',
            'fiducial_derivation_count': len(list(self.root.glob('fid_*.json'))),
            'fiducial_referenced_observations': len(refs),
            'fiducial_errors': errors,
        }


def _verify_store(store):
    result = store.verify()
    if result['status'] != 'PASS':
        raise IntegrityError('Evidence store must pass verification before fiducial processing')


def offline_scan(out, dictionary_name='DICT_4X4_50', limit=40,
                 marker_size_m=None, calibration_path=None):
    cv2 = load_cv()
    store = EvidenceStore(out)
    _verify_store(store)
    fid_store = FiducialStore(store)
    calibration = load_calibration(calibration_path)
    processor = {
        'name_str': 'opencv_aruco_fiducial',
        'opencv_version_str': cv2.__version__,
        'dictionary_name_str': dictionary_name,
        'marker_size_m': marker_size_m,
        'calibration_sha256_hex_str': calibration['calibration_sha256_hex_str'] if calibration else None,
        'coordinate_system_str': 'normalized_pixel_and_optional_calibrated_camera_optical',
    }
    signature = sha256(canonical_bytes(processor))
    processor['processing_signature_sha256_hex_str'] = signature
    paths = sorted(store.observations.glob('obs_*.json'),
                   key=lambda p: (json.loads(p.read_text(encoding='utf-8'))['temporal_binding']['received_monotonic_ns'],p.name))
    if limit is not None:
        if limit < 1:
            raise ValueError('limit must be >= 1')
        paths = paths[:limit]
    created = skipped = found = 0
    for p in paths:
        obs_id = p.stem
        if fid_store.find_existing(obs_id, signature):
            skipped += 1
            continue
        env = store.get_observation(obs_id)
        payload = store._payload_path(env['evidence']['payload_sha256_hex_str']).read_bytes()
        if sha256(payload) != env['evidence']['payload_sha256_hex_str']:
            raise IntegrityError('Payload digest mismatch')
        import numpy as np
        frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise IntegrityError('Observation does not contain a decodable image')
        markers = detect(frame, dictionary_name=dictionary_name, marker_size_m=marker_size_m,
                         calibration=calibration)
        identifier = fid_store.record(observation_id=obs_id, markers=markers, processor=processor)
        created += 1
        found += len(markers)
        print('FIDUCIAL ' + json.dumps({'observation_id': obs_id, 'derivation_id': identifier,
                                         'marker_ids': [x['marker_id_uint'] for x in markers]}))
    return {'status': 'FIDUCIAL_DERIVED_NOT_CHRONOGRAF_ANCHORED', 'processed': created,
            'already_derived': skipped, 'markers_detected_total': found, 'processor_signature_sha256': signature}


def trajectories(out, dictionary_name='DICT_4X4_50', processing_signature=None):
    """Ephemeral view of histories. No fabricated depth or shared clock."""
    store = EvidenceStore(out)
    _verify_store(store)
    records = []
    for path in (store.root / 'fiducials').glob('fid_*.json'):
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if doc['processor']['dictionary_name_str'] != dictionary_name:
            continue
        ref = doc['derived_from']['observation_id_str']
        env = store.get_observation(ref)
        records.append((env['temporal_binding']['received_monotonic_ns'], doc, env))
    records.sort(key=lambda x: x[0])
    signatures = {rec['processor']['processing_signature_sha256_hex_str'] for _,rec,_ in records}
    if processing_signature is None and len(signatures) > 1:
        raise ValueError('Multiple processor signatures in store. Select one with --processing-signature')
    if processing_signature is not None:
        records = [(t,doc,env) for t,doc,env in records if doc['processor']['processing_signature_sha256_hex_str'] == processing_signature]
    seen = {}
    rows = []
    for t, rec, env in records:
        domain = env['temporal_binding']['clock_domain_ref']['clock_domain_id_str']
        for m in rec['interpretation']['markers']:
            mid = m['marker_id_uint']
            xy = m['center_xy_normalized_arr']
            pair = (domain, rec['camera_reference_frame_id_str'], mid)
            row = {'source_observation_id': rec['derived_from']['observation_id_str'],
                   'marker_id': mid, 'received_monotonic_ns': t,
                   'frame_id': rec['camera_reference_frame_id_str'],
                   'center_xy_normalized': xy, 'delta_xy_normalized': None,
                   'velocity_xy_normalized_per_s': None,
                   'pose_camera': m['pose_camera']}
            prior = seen.get(pair)
            if prior and t > prior[0] and t - prior[0] <= 1_500_000_000:
                dt = (t - prior[0]) / 1e9
                delta = [round(xy[i] - prior[1][i], 7) for i in range(2)]
                row['delta_xy_normalized'] = delta
                row['velocity_xy_normalized_per_s'] = [round(x / dt, 7) for x in delta]
            seen[pair] = (t, xy)
            rows.append(row)
    return rows


def live(device, dictionary_name='DICT_4X4_50', width=1280, height=720,
         fps=30, marker_size_m=None, calibration_path=None):
    cv2 = load_cv()
    calibration = load_calibration(calibration_path)
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f'Cannot open camera: {device}')
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    trails = {}
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError('Camera frame read failed')
            markers = detect(frame, dictionary_name=dictionary_name,
                             marker_size_m=marker_size_m, calibration=calibration)
            h, w = frame.shape[:2]
            for m in markers:
                mid = m['marker_id_uint']
                x, y = [int(round(v * s)) for v, s in zip(m['center_xy_normalized_arr'], (w, h))]
                trail = trails.setdefault(mid, [])
                trail.append((x, y))
                if len(trail) > 40:
                    trail.pop(0)
                for a, b in zip(trail[:-1], trail[1:]):
                    cv2.line(frame, a, b, (0, 255, 255), 2)
                cv2.circle(frame, (x, y), 5, (0, 255, 0), -1)
                label = f'tag {mid}  x={x} y={y}'
                if m['pose_camera']:
                    vec = m['pose_camera']['position_xyz_m_arr']
                    label += f'  X={vec[0]:.2f} Y={vec[1]:.2f} Z={vec[2]:.2f}m'
                cv2.putText(frame, label, (max(5, x-30), max(20, y-17)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            cv2.putText(frame, f'OpenRGD fiducial viewer (not a Chronon): {len(markers)} markers',
                        (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.imshow('OpenRGD - Visual Landmarks', frame)
            if cv2.waitKey(1) & 0xff == ord('q'):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
