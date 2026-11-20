"""Optional camera intrinsics calibration, outside OpenRGD and outside the RT loop."""
from __future__ import annotations

import json
from pathlib import Path

from .fiducials import load_cv


def make_checkerboard(path, columns=9, rows=6, square_mm=18):
    """Creates exact-physical-size SVG checkerboard; print at 100% scale.

    columns/rows are INNER corner counts, not square counts.
    """
    if not (3 <= columns <= 30 and 3 <= rows <= 30 and 3 <= square_mm <= 100):
        raise ValueError('Invalid checkerboard geometry')
    margin = 10
    w = (columns + 1) * square_mm + 2 * margin
    h = (rows + 1) * square_mm + 2 * margin
    squares = []
    for row in range(rows+1):
        for col in range(columns+1):
            if (row + col) % 2 == 0:
                squares.append(f'<rect x="{margin + col*square_mm}" y="{margin + row*square_mm}" width="{square_mm}" height="{square_mm}" fill="black"/>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}"><rect width="{w}" height="{h}" fill="white"/>' + ''.join(squares) + '</svg>'
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding='utf-8')
    return str(out)


def calibrate_live(*, device, out, columns=9, rows=6, square_size_m=0.018, width=1280, height=720, fps=30, min_samples=12):
    if columns < 3 or rows < 3 or square_size_m <= 0 or min_samples < 8:
        raise ValueError('Invalid calibration configuration')
    cv2 = load_cv()
    import numpy as np
    pattern = (columns, rows)
    world = np.zeros((rows * columns, 3), np.float32)
    world[:, :2] = np.mgrid[0:columns, 0:rows].T.reshape(-1, 2) * square_size_m
    objpoints, imgpoints = [], []
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f'Unable to open camera: {device}')
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    actual_shape = None
    print(f'Place the checkerboard in different parts of the field; press SPACE to save each visible pose, Q to finish once >= {min_samples}.')
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError('Frame read failed')
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            actual_shape = gray.shape[::-1]
            found, corners = cv2.findChessboardCorners(gray, pattern,
                          cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE)
            refined = None
            if found:
                refined = cv2.cornerSubPix(gray, corners, (11,11), (-1,-1),
                                           (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
                cv2.drawChessboardCorners(frame, pattern, refined, found)
            cv2.putText(frame, f'Calibration: {len(objpoints)} views; detected={found}; SPACE capture; Q finish',
                        (8,30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,0), 2)
            cv2.imshow('OpenRGD - Camera Intrinsics Calibration', frame)
            key = cv2.waitKey(1) & 0xff
            if key == ord(' ') and found:
                objpoints.append(world.copy())
                imgpoints.append(refined.copy())
                print(f'Calibration view {len(objpoints)} acquired')
            elif key == ord('q'):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
    if len(objpoints) < min_samples:
        raise RuntimeError(f'Only {len(objpoints)} calibration views; need at least {min_samples} distinct poses')
    rms, k, d, _, _ = cv2.calibrateCamera(objpoints, imgpoints, actual_shape, None, None)
    if not np.isfinite(rms) or not np.isfinite(k).all() or not np.isfinite(d).all():
        raise RuntimeError('Calibration failed: non-finite parameters')
    result = {
        'schema_ref_str': 'urn:openrgd:experimental:camera-intrinsics-calibration:v0',
        'camera_matrix': k.tolist(),
        'distortion_coefficients': d.reshape(-1).tolist(),
        'width': actual_shape[0], 'height': actual_shape[1],
        'reprojection_rms_px': float(rms),
        'checkerboard_inner_corners': [columns, rows],
        'checkerboard_square_size_m': square_size_m,
        'calibration_views': len(objpoints),
        'coordinate_frame_str': 'camera_optical',
        'extrinsics_status_str': 'NOT_CALIBRATED_TO_WORKSPACE_OR_ROBOT',
        'chronograf_status_str': 'NOT_RESOLVED_BY_CHRONOGRAF',
    }
    path = Path(out).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError('Refuse to overwrite existing calibration file')
    path.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    return result
