"""Offline YOLO consumer of ALREADY RECORDED, immutable visual evidence.

No camera access, no robot actuation, no Chronon/Chronograf write.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from .derivations import DerivationStore, canonical_bytes, sha256
from .evidence import EvidenceStore, IntegrityError


def _weights_info(model_spec: str, resolved: str | None = None) -> dict[str, Any]:
    paths = [Path(model_spec).expanduser()]
    if resolved:
        paths.append(Path(resolved).expanduser())
    for path in paths:
        if path.is_file():
            return {"weights_file_str": path.name,
                    "weights_sha256_hex_str": hashlib.sha256(path.read_bytes()).hexdigest()}
    return {"weights_file_str": Path(model_spec).name,
            "weights_sha256_hex_str": None, "weights_digest_status_str": "UNAVAILABLE"}


def _predictor(model_spec: str, confidence: float, imgsz: int):
    try:
        import cv2
        import numpy as np
        import ultralytics
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("Install perception dependencies: python -m pip install -e '.[perception]'") from exc

    model = YOLO(model_spec)
    processor = {
        "processor_name_str": "ultralytics.yolo",
        "library_version_str": ultralytics.__version__,
        "model": _weights_info(model_spec, getattr(model, "ckpt_path", None)),
        "parameters": {"confidence_threshold_float": confidence, "imgsz_uint": imgsz},
    }

    def run(payload: bytes) -> list[dict[str, Any]]:
        frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise IntegrityError("Could not decode image/jpeg evidence")
        result = model.predict(frame, imgsz=imgsz, conf=confidence, verbose=False)[0]
        width, height = frame.shape[1], frame.shape[0]
        detections = []
        for box in result.boxes:
            index = int(box.cls[0].item())
            xyxy = [float(x) for x in box.xyxy[0].tolist()]
            xyxy = [
                max(0.0, min(1.0, xyxy[0] / width)),
                max(0.0, min(1.0, xyxy[1] / height)),
                max(0.0, min(1.0, xyxy[2] / width)),
                max(0.0, min(1.0, xyxy[3] / height)),
            ]
            detections.append({
                "class_id_uint": index,
                "class_label_str": str(result.names[index]),
                "confidence_float": float(box.conf[0].item()),
                "bbox_xyxy_normalized_arr": xyxy,
            })
        return detections

    return processor, run


def derive(
    *, out: str, model: str = "yolo26n.pt", limit: int | None = 10,
    observation_id: str | None = None,
    confidence: float = 0.35, imgsz: int = 640,
    injected_predictor: Callable[[bytes], list[dict[str, Any]]] | None = None,
    injected_processor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not 0 < confidence <= 1:
        raise ValueError("Confidence must be >0 and <=1")
    if imgsz < 64 or imgsz > 4096:
        raise ValueError("imgsz must be in [64, 4096]")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    store = EvidenceStore(out)
    base_report = store.verify()
    if base_report["status"] != "PASS":
        raise IntegrityError("Evidence archive must pass verification before inference")
    derivations = DerivationStore(store)

    paths = ([store.observations / f"{observation_id}.json"] if observation_id else
             sorted(store.observations.glob("obs_*.json"),
                    key=lambda p: (json.loads(p.read_text())["temporal_binding"].get("received_unix_estimate_ns", 0), p.name)))
    if limit is not None:
        paths = paths[:limit]

    if injected_predictor is None:
        processor, predict = _predictor(model, confidence, imgsz)
    else:
        processor, predict = injected_processor, injected_predictor
        if not isinstance(processor, dict):
            raise ValueError("injected_processor required with injected_predictor")

    # Only source observation content, weights+version and options define a
    # processing identity; each actual inference gets its own creation timestamp.
    signature_base = {k: v for k, v in processor.items() if k != "processing_signature_sha256_hex_str"}
    signature = sha256(canonical_bytes(signature_base))
    processor = {**signature_base, "processing_signature_sha256_hex_str": signature}

    created, skipped, ids = 0, 0, []
    for path in paths:
        envelope = store.get_observation(path.stem)
        obs_id = envelope["observation_id_str"]
        if derivations.find_existing(obs_id, signature):
            skipped += 1
            continue
        evidence = envelope["evidence"]
        expected = evidence["payload_sha256_hex_str"]
        payload = store._payload_path(expected).read_bytes()
        if sha256(payload) != expected:
            raise IntegrityError("Source payload changed since initial verification")
        start = time.monotonic_ns()
        detections = predict(payload)
        result = derivations.create(
            observation_id=obs_id,
            processor=processor,
            detections=detections,
            inference_started_monotonic_ns=start,
        )
        created += 1
        ids.append(result["derivation_id_str"])
        print("DERIVATION " + json.dumps({
            "derivation_id": result["derivation_id_str"],
            "derived_from_observation_id": obs_id,
            "objects": len(detections),
            "labels": [o["class_label_str"] for o in detections],
        }, ensure_ascii=False))

    return {"status": "DERIVED_NOT_CHRONOGRAF_ANCHORED",
            "processed": created, "already_derived": skipped,
            "derivation_ids": ids,
            "processor_signature_sha256": signature}
