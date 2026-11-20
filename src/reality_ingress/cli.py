from __future__ import annotations

import argparse
import json
from pathlib import Path

from .camera import DEFAULT_DEVICE, DEFAULT_SOURCE_ID, capture
from .evidence import EvidenceStore


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenRGD Reality Ingress experimental v0.4")
    commands = parser.add_subparsers(dest="command", required=True)

    record = commands.add_parser("capture", help="Capture a bounded local observation set")
    record.add_argument("--device", default=DEFAULT_DEVICE)
    record.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    record.add_argument("--reference-frame", default="frame.camera.c920.03CB417F")
    record.add_argument("--out", default="./reality-evidence")
    record.add_argument("--seconds", type=float, default=20)
    record.add_argument("--sample-hz", type=float, default=2)
    record.add_argument("--width", type=int, default=1280)
    record.add_argument("--height", type=int, default=720)
    record.add_argument("--fps", type=int, default=30)
    record.add_argument("--jpeg-quality", type=int, default=90)

    verify = commands.add_parser("verify", help="Check stored payload integrity")
    verify.add_argument("--out", default="./reality-evidence")

    inspect = commands.add_parser("inspect", help="Read an observation without interpretation")
    inspect.add_argument("--out", default="./reality-evidence")
    inspect.add_argument("--observation-id", required=True)

    derive_command = commands.add_parser("derive", help="Analyze already stored JPEG evidence, without opening the camera")
    derive_command.add_argument("--out", default="./reality-evidence")
    derive_command.add_argument("--model", default="yolo26n.pt")
    derive_command.add_argument("--limit", type=int, default=10)
    derive_command.add_argument("--observation-id")
    derive_command.add_argument("--confidence", type=float, default=0.35)
    derive_command.add_argument("--imgsz", type=int, default=640)

    markers = commands.add_parser("markers-generate", help="Generate printable fiducial PNGs (measure actual printed black square)")
    markers.add_argument("--out", default="./rgd-markers")
    markers.add_argument("--ids", type=int, nargs="+", default=[11, 12, 13])
    markers.add_argument("--dictionary", default="DICT_4X4_50")
    markers.add_argument("--side-mm", type=float, default=36.0)

    scan = commands.add_parser("markers-scan", help="Append fiducial derivations to immutable existing image evidence")
    scan.add_argument("--out", default="./reality-evidence")
    scan.add_argument("--dictionary", default="DICT_4X4_50")
    scan.add_argument("--limit", type=int, default=100)
    scan.add_argument("--calibration", default=None)
    scan.add_argument("--marker-size-m", type=float, default=None)

    tracks = commands.add_parser("markers-tracks", help="Display image-plane motion of persistent marker IDs (non-canonical view)")
    tracks.add_argument("--out", default="./reality-evidence")
    tracks.add_argument("--dictionary", default="DICT_4X4_50")
    tracks.add_argument("--processing-signature", default=None)

    mlive = commands.add_parser("markers-live", help="Show live marker centers and trails without writing evidence")
    mlive.add_argument("--device", default=DEFAULT_DEVICE)
    mlive.add_argument("--dictionary", default="DICT_4X4_50")
    mlive.add_argument("--calibration", default=None)
    mlive.add_argument("--marker-size-m", type=float, default=None)

    board = commands.add_parser("checkerboard-generate", help="Generate physical-size SVG checkerboard, print at 100%%")
    board.add_argument("--out", default="./camera-checkerboard.svg")
    board.add_argument("--columns", type=int, default=9)
    board.add_argument("--rows", type=int, default=6)
    board.add_argument("--square-mm", type=int, default=18)

    calibration = commands.add_parser("camera-calibrate", help="Calibrate C920 intrinsics from distinct checkerboard views")
    calibration.add_argument("--device", default=DEFAULT_DEVICE)
    calibration.add_argument("--out", default="./camera-intrinsics.json")
    calibration.add_argument("--columns", type=int, default=9)
    calibration.add_argument("--rows", type=int, default=6)
    calibration.add_argument("--square-size-m", type=float, default=0.018)
    calibration.add_argument("--min-samples", type=int, default=12)

    generic = commands.add_parser("ingest-jsonl", help="Import generic source-stamped JSONL observations without changing their sample time")
    generic.add_argument("--file", required=True)
    generic.add_argument("--out", default="./reality-evidence")

    synthetic = commands.add_parser("synthetic-telemetry", help="Produce clearly labeled synthetic telemetry for a zero-hardware dry run")
    synthetic.add_argument("--file", required=True)
    synthetic.add_argument("--count", type=int, default=10)

    fakepair = commands.add_parser("synthetic-pairs", help="Create clearly labeled fake camera+body evidence to validate pairing")
    fakepair.add_argument("--out", required=True)
    fakepair.add_argument("--count", type=int, default=5)

    probe = commands.add_parser("temporal-probe", help="Diagnostic same-host receipt-time proximity only; not Chronograf sync")
    probe.add_argument("--out", default="./reality-evidence")
    probe.add_argument("--left-modality", default="rgb")
    probe.add_argument("--right-modality", default="joint_state")
    probe.add_argument("--max-offset-ms", type=float, default=100.0)
    probe.add_argument("--max-pairs", type=int, default=100)

    args = parser.parse_args()
    if args.command == "ingest-jsonl":
        from .generic import ingest_jsonl
        print(json.dumps(ingest_jsonl(EvidenceStore(args.out), args.file), indent=2))
    elif args.command == "synthetic-telemetry":
        from .synthetic import make_synthetic_jsonl
        print(json.dumps(make_synthetic_jsonl(args.file, args.count), indent=2))
    elif args.command == "synthetic-pairs":
        from .synthetic import make_synthetic_pair_fixture
        print(json.dumps(make_synthetic_pair_fixture(args.out, args.count), indent=2))
    elif args.command == "temporal-probe":
        from .temporal_probe import temporal_probe
        result = temporal_probe(EvidenceStore(args.out), left_modality=args.left_modality,
                                right_modality=args.right_modality,
                                max_offset_ms=args.max_offset_ms, max_pairs=args.max_pairs)
        print(json.dumps(result, indent=2))
    elif args.command == "capture":
        store = EvidenceStore(args.out)
        result = capture(
            device=args.device,
            store=store,
            source_id=args.source_id,
            reference_frame_id=args.reference_frame,
            seconds=args.seconds,
            sample_hz=args.sample_hz,
            width=args.width,
            height=args.height,
            fps=args.fps,
            jpeg_quality=args.jpeg_quality,
        )
        print("SUMMARY " + json.dumps(result, indent=2))
    elif args.command == "verify":
        result = EvidenceStore(args.out).verify()
        print(json.dumps(result, indent=2))
        if result["status"] != "PASS":
            raise SystemExit(1)
    elif args.command == "inspect":
        print(json.dumps(EvidenceStore(args.out).get_observation(args.observation_id), indent=2))
    elif args.command == "markers-generate":
        from .fiducials import make_markers
        print(json.dumps(make_markers(args.out, args.ids, args.dictionary, side_mm=args.side_mm), indent=2))
    elif args.command == "markers-scan":
        from .fiducials import offline_scan
        print("SUMMARY " + json.dumps(offline_scan(
            args.out, dictionary_name=args.dictionary, limit=args.limit,
            marker_size_m=args.marker_size_m, calibration_path=args.calibration), indent=2))
    elif args.command == "markers-tracks":
        from .fiducials import trajectories
        print(json.dumps(trajectories(args.out, dictionary_name=args.dictionary, processing_signature=args.processing_signature), indent=2))
    elif args.command == "markers-live":
        from .fiducials import live
        live(args.device, dictionary_name=args.dictionary,
             marker_size_m=args.marker_size_m, calibration_path=args.calibration)
    elif args.command == "checkerboard-generate":
        from .calibration import make_checkerboard
        print(make_checkerboard(args.out, args.columns, args.rows, args.square_mm))
    elif args.command == "camera-calibrate":
        from .calibration import calibrate_live
        print(json.dumps(calibrate_live(
            device=args.device, out=args.out, columns=args.columns, rows=args.rows,
            square_size_m=args.square_size_m, min_samples=args.min_samples), indent=2))
    elif args.command == "derive":
        from .perception import derive
        result = derive(
            out=args.out, model=args.model, limit=args.limit,
            observation_id=args.observation_id, confidence=args.confidence, imgsz=args.imgsz,
        )
        print("SUMMARY " + json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
