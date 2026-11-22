"""Single-camera V4L2/OpenCV Synapse; independent of agent and cognition."""
from __future__ import annotations

import json
import time
from typing import Any

from .evidence import EvidenceStore
from .timebase import receive_stamp

DEFAULT_DEVICE = "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_03CB417F-video-index0"
DEFAULT_SOURCE_ID = "sensor.camera.c920.03CB417F"


def capture(
    *,
    device: str,
    store: EvidenceStore,
    source_id: str,
    reference_frame_id: str,
    seconds: float = 20,
    sample_hz: float = 2,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    jpeg_quality: int = 90,
) -> dict[str, Any]:
    # Delayed import keeps validation/test operation independent of OpenCV.
    import cv2

    if not 0 < seconds <= 3600:
        raise ValueError("seconds must be 0 < value <= 3600")
    if not 0 < sample_hz <= fps:
        raise ValueError("sample_hz must be >0 and <= fps")
    if not 1 <= jpeg_quality <= 100:
        raise ValueError("jpeg_quality must be 1..100")

    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open camera: {device}")

    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        actual = {
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps_requested": fps,
            "fps_reported": cap.get(cv2.CAP_PROP_FPS),
            "fourcc_reported": "".join(chr((int(cap.get(cv2.CAP_PROP_FOURCC)) >> (8 * i)) & 0xFF) for i in range(4)),
        }
        print("CAMERA_PROFILE " + json.dumps(actual))

        start = time.monotonic()
        next_save = start
        period = 1.0 / sample_hz
        frames_read = 0
        observations_saved = 0
        saved_ids = []
        read_failures = 0

        while time.monotonic() - start < seconds:
            ok, frame = cap.read()
            stamp = receive_stamp()  # immediately after read returns
            if not ok:
                read_failures += 1
                if read_failures > 30:
                    raise RuntimeError("More than 30 frame-read failures")
                continue

            frames_read += 1
            now = time.monotonic()
            if now < next_save:
                continue
            next_save = now + period

            success, encoded = cv2.imencode(
                ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
            )
            if not success:
                raise RuntimeError("Unable to encode decoded frame")

            envelope = store.record(
                data=encoded.tobytes(),
                source_id=source_id,
                modality="rgb",
                reference_frame_id=reference_frame_id,
                sequence=frames_read,
                timestamp=stamp,
                media_type="image/jpeg",
                representation={
                    "kind_str": "decoded_bgr_reencoded_jpeg",
                    "lossless_bool": False,
                    "jpeg_quality_uint": jpeg_quality,
                    "width_uint": int(frame.shape[1]),
                    "height_uint": int(frame.shape[0]),
                    "requested_v4l2_fourcc_str": "MJPG",
                },
            )
            observations_saved += 1
            saved_ids.append(envelope["observation_id_str"])
            print(
                "OBSERVATION "
                + json.dumps(
                    {"observation_id": envelope["observation_id_str"],
                     "frame_seq": frames_read,
                     "sha256": envelope["evidence"]["payload_sha256_hex_str"],
                     "received_monotonic_ns": stamp["received_monotonic_ns"]}
                )
            )

        elapsed = time.monotonic() - start
        return {
            "status": "RECORDED_NOT_CHRONOGRAF_ANCHORED",
            "source_id": source_id,
            "duration_s": round(elapsed, 3),
            "frames_read": frames_read,
            "read_failures": read_failures,
            "observations_saved": observations_saved,
            "delivered_frames_read_per_second": round(frames_read / elapsed, 2),
            "observation_ids": saved_ids,
            "camera_profile": actual,
        }
    finally:
        cap.release()
