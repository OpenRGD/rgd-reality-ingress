# OpenRGD Reality Ingress — experimental v0.4 (Multi-Source & Temporal Probe)

**What v0.4 changes:** Reality Ingress now accepts **generic external source-stamped JSONL telemetry** (including joint state) without importing LeRobot or opening a motor serial port. Camera/fiducial/YOLO support from v0.3 remains intact. A diagnostic correlator pairs observations by Linux **same-boot, same-host userspace receipt time**, never claiming sensor exposure-time synchronization, global Chronograf anchoring or physical causality.

**Engineering maturity:** adapter-side experimental schemas, NOT accepted canonical Agent Contracts. Core `OpenRGD/openrgd` unchanged. No physical SO101 joint read was performed in the artifact-building environment. This is a testable bridge, not verified C920↔SO101 synchronization.

## Immediate dry run on Fedora (NO robot, NO camera)

Unzip next to v0.3 in `~/workspace/robotics`, then:

```bash
conda activate rgd-perception
cd ~/workspace/robotics/openrgd-reality-ingress-v0.4
python -m pip install -e '.[fiducials]'
python -m unittest discover -s tests -v

# Mock data are visibly labeled SYNTHETIC and written to a fresh directory.
rgd-reality-ingress synthetic-pairs \
  --out ~/workspace/robotics/reality-evidence-v04-synthetic --count 5
rgd-reality-ingress verify \
  --out ~/workspace/robotics/reality-evidence-v04-synthetic
rgd-reality-ingress temporal-probe \
  --out ~/workspace/robotics/reality-evidence-v04-synthetic --max-offset-ms 10
```

Expected: `verify: PASS`, `pair_count: 5`, reported +3ms **simulated** receipt-time offsets. This fixture is **not actual camera or robot evidence**. It will refuse to mix itself into a nonempty evidence store.

## Generic-source JSONL API

Use `TelemetryJSONL` in an **already running, already connected, non-real-time** acquisition/teleoperation process that has legal access to the robot observation. The hook never calls `connect`, `configure`, `send_action`, `disable_torque` or `get_observation` itself. Do **not** start a second controller on the same servo bus; some LeRobot `connect()` implementations configure actuators and can trigger calibration-related behavior.

Integration snippet to insert into the existing observation path **after** it already calls `robot.get_observation()`:

```python
from reality_ingress.telemetry_hook import TelemetryJSONL

publisher = TelemetryJSONL(
    '~/workspace/robotics/telemetry-session-001.jsonl',
    source_id='source.telemetry.arm_A',       # Source identity is NOT agent/self ownership.
    reference_frame_id='frame.body.arm_A',
    producer='LeRobot.existing_loop.readonly_hook',
)
try:
    # Inside an existing, NON-REAL-TIME observation loop owned by LeRobot:
    # observation = robot.get_observation()
    # publisher.publish(observation)   # Immediately after the read returns.
    # (Keep the original control code unchanged; these lines are only a hook.)
    pass
finally:
    publisher.close()
```

`publish()` captures `time.monotonic_ns` from the host and passes data to a **bounded background writer**; it does no camera opening, database access, motor commands or disk writes in the foreground callback. Full LeRobot wiring **depends on your existing teleop program and installed version**, and is intentionally not guessed here. The hook filters only numeric observation keys ending in `.pos`, `.vel`, `.torque`; it excludes camera arrays. For each measurement, unit = `SOURCE_NATIVE_UNSPECIFIED` until source-specific units are verified. If none are found it errors rather than fabricating joint state.

### Capture one genuine two-source session (after hooking into your existing LeRobot loop)

1. Start the LeRobot observation/teleop process with the hook active, writing session-specific JSONL. Do not run two programs against the same motor port.
2. Simultaneously, start camera capture **in the separate `rgd-perception` environment** (one camera owner):

```bash
rgd-reality-ingress capture \
 --device /dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_03CB417F-video-index0 \
 --seconds 20 --sample-hz 10 \
 --out ~/workspace/robotics/reality-evidence-session-001
```

3. After the hook is closed/flushed, import genuine telemetry without restamping it at import time:

```bash
rgd-reality-ingress ingest-jsonl \
 --file ~/workspace/robotics/telemetry-session-001.jsonl \
 --out ~/workspace/robotics/reality-evidence-session-001

rgd-reality-ingress verify --out ~/workspace/robotics/reality-evidence-session-001
rgd-reality-ingress temporal-probe \
 --out ~/workspace/robotics/reality-evidence-session-001 \
 --left-modality rgb --right-modality joint_state --max-offset-ms 100
```

A zero-pair report is NOT necessarily an error: the two streams may have been recorded at different times, different Linux boots, or more than 100ms apart. The diagnostic refuses to pair across different clock-domain identities; it never falls back to wall clock timestamps without cross-domain evidence.

## Standalone ingest contract

A generic JSONL entry looks like:

```json
{
  "schema_ref_str": "urn:openrgd:experimental:reality-ingress:source-sample:v0",
  "producer_str": "external-source-adapter",
  "source": {
    "source_id_str": "source.telemetry.arm_A",
    "modality_str": "joint_state",
    "reference_frame_id_str": "frame.body.arm_A",
    "sample_sequence_uint": 1
  },
  "temporal_binding": {
    "received_monotonic_ns": 123456789000,
    "received_unix_estimate_ns": 1790000000000000000,
    "host_wall_pair_span_ns": 200,
    "clock_domain_ref": {
      "clock_domain_id_str": "chronos.monotonic.boot:REAL_BOOT_ID",
      "clock_kind_enum_str": "MONOTONIC",
      "boot_id_str": "REAL_BOOT_ID"
    },
    "source_time": null,
    "source_time_status_str": "UNKNOWN_NOT_EXPOSED_BY_SOURCE"
  },
  "payload": {
    "measurements": {"shoulder_pan.pos": {"value": 42.0, "unit_str": "SOURCE_NATIVE_UNSPECIFIED"}}
  }
}
```

The example timestamp numbers and `REAL_BOOT_ID` **are documentation placeholders**, not physical readings. Actual capture must use producer-side measured time; do not type fabricated timestamps in a real telemetry file. `source_time = null` means exposure/encoder-latch time is **unknown**, not assumed equal to userspace receive time. **JSON import is idempotent**, content-committed and does not overwrite prior observations. Native units, frame transforms, offset-to-link, and agent ownership are external registries, never inferred by Ingress.

## Fiducial print-day protocol

The v0.3 commands still work unchanged:

```bash
rgd-reality-ingress markers-live --device "$CAM"
rgd-reality-ingress camera-calibrate --device "$CAM" \
  --out ~/workspace/robotics/c920-intrinsics-720p.json
```

- Print the `OpenRGD_Marker_Kit_A4_v0.3.pdf` at 100% actual size. Test the 100mm ruler and 18mm checkerboard square.
- For adhesive paper, apply tags flat to **rigid plates**, never bend the black square around a rounded arm or mount on servo cabling.
- Identify IDs on screen before attachment, beginning with base=11; link-to-marker mapping belongs in an external installation registry.
- Intrinsics calibration needs diverse chessboard viewpoints; marker size in meters must match **each marker ID**. Current `markers-scan --marker-size-m` takes one constant marker size per run, so group uniform-size IDs or extend per-ID sizes before mixed metric 3D pose.
- A camera-frame pose is NOT yet robot-base-frame XYZ. Calibrate `T_base_camera` and `T_link_marker` separately after geometric registration.
- Telemetry and marker observations only become a validated **cross-modal body tracking** experiment after they are recorded together and their temporal limitations are measured.

## Scope and caveats

- v0.4 deliberately does NOT implement Chronograf TimeAtoms, Chronon persistence, a canonical Reality Ingress schema, a direct LeRobot follower connector, shared multi-host clock, 3D body estimator or automatic SELF/OTHER binding.
- Nearest timestamps are **host userspace availability proximity**, not physical simultaneity. Camera exposure, USB buffering and controller read latency are unmeasured; a small offset does NOT mean tight physical synchrony.
- Content-addressed records detect ordinary tampering, **not authenticated provenance**. Archives may include personal images and should not be committed or published.
- v0.4 retains the original v0.3 `capture`, `derive`, `markers-*`, `checkerboard-generate`, `camera-calibrate`, `verify` interfaces and archives.
- `temporal-probe` is an ephemeral diagnostic and does not create Chronons or permanent agent relationships.

**Testing:** 34 local unit tests passed (21 original v0.3 + 13 multi-source). Genuine SO101 joint telemetry still requires integration into the existing LeRobot observation owner and a fresh, simultaneous camera session.

---

## Previous v0.3 capabilities (unchanged)

# OpenRGD Reality Ingress — experimental v0.3 (Visual Landmarks)

**v0.3 adds agnostic visual fiducial tracking as a SECONDARY derived processor.** This is not SO101 recognition, entity identity, embodiment binding or a canonical Chronon. The camera and the evidences remain agent-independent. All v0.1/v0.2 commands and archives remain compatible.

## QUICK START — Fedora / SO101 visual-landmark experiment

Unzip `openrgd-reality-ingress-v0.3.zip` into `~/workspace/robotics`. Keep the previously captured `reality-evidence-*` directories untouched.

```bash
conda activate rgd-perception
cd ~/workspace/robotics/openrgd-reality-ingress-v0.3
python -m pip install -e '.[fiducials]'
python -m unittest discover -s tests -v
python -c 'import cv2; print(cv2.__version__, hasattr(cv2,"aruco"))'
```

If your OpenCV build has no `cv2.aruco`, stop before installing competing OpenCV wheel variants in the same environment; use a separate environment with a compatible ArUco-capable build.

### Step A — print three IDs with correct metric size

```bash
rgd-reality-ingress markers-generate --ids 11 12 13 --side-mm 36 --out ~/workspace/robotics/rgd-markers
```

Open the generated **SVG** files, print **at 100% / actual size** without "fit to paper", and use a ruler to verify the black marker outer square is **36 mm**. The PNGs are provided only for inspection; their physical size depends on printer scaling. Print flat with clean white margins and rigidly attach tags (NOT to freely hanging wires):

- 11 → stable workbench/base fixture (fixed relative to the SO101's base)
- 12 → rigid moving arm segment (upper arm / forearm)
- 13 → rigid wrist/gripper carrier **only if it fits safely**

**This mapping is an external experiment/deployment registry; Reality Ingress NEVER treats IDs as body part or SELF.** Keep tags visible to the C920 throughout slow motion. Ensure tags, their mounts and any cables cannot catch in joint mechanisms. Do not force powered joints by hand; use a previously verified, safety-gated LeRobot control procedure when you later test movement.

### Step B — visualize tag tracking WITHOUT reading/altering the evidence archive

Close any other camera process, then:

```bash
CAM=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_03CB417F-video-index0
rgd-reality-ingress markers-live --device "$CAM"
```

Shows ID 11/12/13, their detected centers and 2D trails. Press `q` to quit. Live preview is **not** a recorded ObservationEnvelope/Chronon, and the camera can be opened by only one process at a time.

### Step C — record an immutable new session and derive tracker observations

```bash
rgd-reality-ingress capture --device "$CAM" --seconds 20 --sample-hz 10 \
  --out ~/workspace/robotics/reality-evidence-landmarks-01
rgd-reality-ingress markers-scan --out ~/workspace/robotics/reality-evidence-landmarks-01 --limit 200
rgd-reality-ingress markers-tracks --out ~/workspace/robotics/reality-evidence-landmarks-01
rgd-reality-ingress verify --out ~/workspace/robotics/reality-evidence-landmarks-01
```

`markers-scan` saves **append-only and independently content-hashed fiducial derivations** in `fiducials/`, referring to the original unchanged `observations/` and `payloads/`. Each marker preserves ID, quadrilateral, normalized center, camera reference frame and processing time. `markers-tracks` computes *2D* motion by marker ID over host receipt times (not exposure times), and restarts the velocity estimate after long gaps. Detection absence must remain unknown/occluded, never "position = 0". `verify` validates both original v0.2 and new v0.3 records.

### Step D — OPTIONAL metric 3D pose in the CAMERA frame

A single uncalibrated C920 **cannot** turn arbitrary point pixel displacement into true 3D displacement. Known-size square fiducials, camera intrinsics and PnP enable an estimated 6-DoF pose **relative to the calibrated camera frame**. This is NOT yet the world frame or robot base frame.

First create an A4-size checkerboard (9x6 **inner corners**, 18mm squares):

```bash
rgd-reality-ingress checkerboard-generate --out ~/workspace/robotics/camera-board.svg
```

Print at actual size (100%) on a flat sheet; verify an individual square side really measures 18mm. During calibration, keep the camera fixed in the same zoom/resolution/focus profile as recording; only move the checkerboard, capturing diverse tilt, distance and field positions. Temporarily close the camera viewer. Then:

```bash
rgd-reality-ingress camera-calibrate --device "$CAM" \
  --out ~/workspace/robotics/c920-intrinsics-720p.json
```

In the window, press **SPACE** to capture a well-detected view, collect at least **12 varied views**, and press **q** to calibrate. Inspect `reprojection_rms_px`; a lower value is preferable, but a finite low RMS does not guarantee metric accuracy if square size, print scale, focus, or camera mounting is wrong.

Now record a **new** 720p marker-equipped session (or apply this to an existing 720p session containing markers), then run:

```bash
rgd-reality-ingress markers-scan --out ~/workspace/robotics/reality-evidence-landmarks-01 \
  --limit 200 --calibration ~/workspace/robotics/c920-intrinsics-720p.json \
  --marker-size-m 0.036
```

The resulting `pose_camera.position_xyz_m_arr`, Rodrigues rotation vector and per-marker reprojection error are **estimates**, not ground truth. If the same session was analyzed earlier without calibration, multiple processor signatures will coexist; use the signature printed by `markers-scan` with `markers-tracks --processing-signature <hash>`.

**To get world/robot-base XYZ** you still need the rigid camera-to-workspace/base transform (`T_world_camera` or `T_base_camera`) and, for link movement, marker-to-link rigid mounting offsets (`T_link_marker`). Those registrations belong outside Reality Ingress. A single image cannot reliably recover obstructed or partially hidden joints. Optional future read-only LeRobot joint-state evidence can compare visual link pose with forward kinematics through temporally correlated but non-faked timestamps.

### What this DOES NOT implement

- NO SO101-specific conditional logic, motor commands, or Somatic Loop writes.
- NO claim of camera exposure timestamp, shared Chronograf clock, TimeAtom, real-time body synchronization, or Chronon persistence.
- NO detection of an unmarked robot or universal trained robot segmentation.
- NO inference of `SELF` from marker ID or image label.
- NO guarantee of true 3D accuracy without calibration, mounting transforms, and quality checks.
- NO persistent world-entity tracker; only known visual fiducial IDs and local image-plane trajectories.

---

## Previous v0.2 capabilities

**v0.2 objective:** attach append-only, verifiable **perception derivations** to the **same camera observations** already recorded by v0.1. This is a non-actuating, non-canonical adapter experiment. No camera access is necessary during offline inference.

## What is supported

- v0.1 functionality is retained: camera `capture`, `inspect`, payload SHA-256, observation records, and `verify`.
- **New `derive` command**: consume an existing stored JPEG referenced by an `ObservationEnvelope`; run YOLO; write one derivation record containing detected class, confidence and normalized bounding box.
- Each derivation binds to the immutable evidence using `observation_id_str`, its exact envelope-byte SHA-256, and stored JPEG SHA-256.
- Derivation records are independently content-addressed and stored write-once (`der_<sha256>.json`). Multiple processors can derive different meanings from the same observation; the source does not change.
- `verify` checks observed images, derived records, content commitments, and that existing source envelopes still match the snapshots referenced by derivations.
- A replay with unchanged model + options skips already-derived samples. A model upgrade or changed parameters creates a different processor signature and new derivations; no old results are overwritten.
- An **empty archive returns `EMPTY` instead of `PASS`**.
- No `SELF` class is accepted in detector outputs; that is agent-relative knowledge created downstream by identity/world-model.

**This is NOT a Chronon/Chronograf integration.** Timestamp measurement during capture remains the Linux host's userspace receive time, not C920 exposure time. Inference has a *separate*, later host processing time. No global synchrony, canonical TimeAtom, Chronograf anchor, world entity tracking, or distributed streaming is claimed.

## Fedora — upgrade from v0.1

Keep your existing observation archive unchanged. Extract the new ZIP alongside the existing `openrgd-reality-ingress-v0.1` folder:

```bash
cd ~/workspace/robotics
unzip openrgd-reality-ingress-v0.2.zip
conda activate lerobot
cd openrgd-reality-ingress-v0.2
python -m pip install -e .
python -m unittest discover -s tests -v
```

The command `rgd-reality-ingress` is installed with the active Python environment. Check:

```bash
which rgd-reality-ingress
python -c 'import reality_ingress; print(reality_ingress.__file__)'
```

Before installing additional model dependencies, see what the environment has:

```bash
python -c 'import cv2, ultralytics; print(cv2.__version__, ultralytics.__version__)'
```

If `ultralytics` is absent, the optional dependency set is:

```bash
python -m pip install -e '.[perception]'
```

Installing Ultralytics may modify ML dependencies such as PyTorch. Use a dedicated Python environment if you want to keep the LeRobot environment pinned. v0.2's offline `derive` command does not need LeRobot itself.

## Run offline detection on the 75 existing camera observations

Start with only ten:

```bash
rgd-reality-ingress derive \
  --out ~/workspace/robotics/reality-evidence \
  --model yolo26n.pt \
  --limit 10 \
  --confidence 0.35
```

`yolo26n.pt` is an example model reference from the earlier test; point `--model` to your existing downloaded weights if they live elsewhere. Ultralytics may try to download the weights on the first use when that file is not found locally.

Then check:

```bash
rgd-reality-ingress verify --out ~/workspace/robotics/reality-evidence
```

Expected non-fabricated output shape:

```json
{
  "status": "PASS",
  "observation_count": 75,
  "unique_payload_count": 75,
  "derivation_count": 10,
  "referenced_observation_count": 10,
  "errors": []
}
```

The exact counts depend on how many observations you process. To process the complete existing archive, rerun `derive --limit 75`; the existing ten processor/observation combinations will be skipped by design.

## On-disk layout

```text
reality-evidence/
├── payloads/              # v0.1 content-addressed JPEG representations; unchanged
├── observations/          # v0.1 write-once ObservationEnvelope JSON; unchanged
└── derivations/           # NEW immutable derived claims, each with source refs and hash
    └── der_....json
```

## Integrity and semantics

- A JPEG is **the stored representation of decoded and re-encoded C920 pixels**, not the original MJPEG UVC packet; do not call it camera-native raw evidence.
- YOLO class labels are **model hypotheses**, not persistent entity IDs, agent identities, or world truth.
- `confidence_float` belongs to detector output, **not** timestamp quality.
- A missing YOLO class for the SO101 arm does not mean the arm is absent; `SELF` must be resolved later by a body-entity binding, not by tagging pixels inside the shared source.
- SHA-256 is an **integrity commitment**, not authenticated provenance or a proof of capture. The system does not digitally sign evidence and cannot prevent a fully privileged attacker from replacing an entire archive consistently.
- Old observations do not gain exposure timestamps or Chronograf synchronization retroactively.
- The snapshot of a source observation envelope is hash-bound when the first derivation is created; v0.1 observations without derivations still rely on payload hash checks rather than an independently signed manifest.
- Local stored images may contain people or private surroundings. Keep the evidence archive private and out of Git.

## Verified scope

Local synthetic suite: **16 unit tests**, including all original seven v0.1 tests, append-only derivations, source integrity, tampering detection, no `SELF`, and offline re-run idempotency.

The YOLO weights/model inference path is not tested against a real physical camera in the artifact-building environment. That must be verified on the target Fedora computer. The adapter does not yet include a VLM, live image feed, on-device body ID, SO101 state, agent distribution service, Chronograf consumer or Chronon assembler.

## Future gates

1. Validate 10 real stored samples with YOLO and inspect inferred object labels.
2. Handle offline batch results in an agent-agnostic world-model/track consumer; distinguish detection vs persistent entity.
3. Add a single-owner streaming camera service with bounded queues and receiver consumer interfaces when real-time inference is needed.
4. Add read-only SO101 joint evidence on a separate acquisition path; keep camera, disk and inference outside the Somatic Loop real-time.
5. Wire Chronograf using actual cross-domain clock evidence, then link compatible `ChrononSpaceRef` / `ChrononRelation` through the finalized contracts. No simulated global timestamps.

**Authority:** `OpenRGD/openrgd` → `contracts/agent/v0.1.0/` (candidate, non-normative); this experimental adapter does not modify the Canonical Core.


## v0.3 validation and evidence boundary

Local validation in the artifact-building environment: **21 tests passed** (16 original v0.2 plus 5 fiducial/calibration/track tests). These include synthetic generated visual tags, 2D motion across two separately stored observations, optional calibrated camera-frame pose, source byte retention, tamper detection and idempotency. Real fiducial detection, calibration quality, visual tracking under motion, and synchronization against LeRobot telemetry **remain to be tested on the Fedora workstation**.

New record type `urn:openrgd:experimental:reality-ingress:fiducial-derivation:v0` remains an adapter-side, explicitly non-normative format. No current OpenRGD Agent Contract is claimed to standardize it.
