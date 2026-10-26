# Reality Ingress ↔ Perception — candidate boundary

Status: **proposal, not normative**. Reconcile against the actual Fedora
`openrgd-reality-ingress-v0.4` implementation before promoting a versioned schema.

## Responsibility split

| Operation | Reality Ingress | RGD Perception | Other authority |
| --- | --- | --- | --- |
| Read UVC camera / USB microphone / IMU | Owns capture adapters | No | OS device drivers |
| Preserve original payload, hash and source | Owns | References inputs only | Persistent store |
| Source/receipt clock metadata | Records with provenance | Carries references | Chronograf for canonical time |
| Deterministic left/right crops of stereo SBS | May expose separately with relation to raw parent | Consumes | RGD Calibration for geometry |
| Stereo depth or disparity estimation | Never authoritative | Owns derived result | RGD Calibration for parameters |
| Detections / YOLO / segmentation / tracking | Never authoritative | Owns derived result | Model provider |
| Speech recognition / interpretation | Preserves audio observation | Owns derived result | Voice runtime for dialog |
| Memory / Chronon persistence | No authority | No authority | RGD-Physics / Chronograf |
| Motion, CAN, actuation | Forbidden | Forbidden | Safety-gated Somatic runtime |

## Provenance invariants

1. Input evidence is immutable: later interpretations never modify originals.
2. A *source* (e.g. external Logitech) is distinct from the *robot*, from
   the *observer*, and from the *subject visible in an image*.
3. Each derived result references one or more real input evidence IDs/hashes
   and its processor/model identity/version, parameters, and calibration ref.
4. Only assert the timing the sensor/transport really gives; monotonic receipt
   time is not the hardware exposure time, and a timestamp is not a Chronograf
   anchor by itself.
5. Calibration metadata is versioned and may be `experimental`. A visual
   depth prediction is **not** a certified metric distance by default.
6. Both modules stay non-actuating. Their outputs cannot directly invoke a
   Body Adapter, actuators or the safety gate.
7. Derived result stores may be rebuilt; canonical Chronon history is owned
   outside these modules and must preserve original provenance.

## Paky-01 example

1. OCCHI is observed as one hardware stereo side-by-side MJPEG frame
   (2560×720). Ingress stores original bytes/hash, source UID, receipt timestamp
   and acquisition parameters.
2. Ingress may expose A/B views with deterministic crop transformation metadata,
   *without* claiming physical left/right until verified.
3. Perception consumes input refs and a **candidate** CAL profile to estimate
   disparity/depth (and quality/missing regions). It records model, parameters,
   confidence/uncertainty and input refs.
4. Console displays observations and derived outputs separately. Chronograf,
   Chronon history and memory integration will use explicit adapters only after
   interface contracts are verified.

## To verify before v0.1 promotion

- Compare v0.4 Fedora `model.py`, `evidence.py`, `generic.py`,
  `derivations.py`, `perception.py`, `calibration.py`, `timebase.py`,
  `consumers.py` and tests.
- Preserve v0.4 observation hash identity and deduplication semantics.
- Agree on one versioned transport/serialization profile with
  `OpenRGD/rgd-perception`; do not silently promote this document to
  Canonical Core standard.
- Define failure and partial-observation states and privacy/retention policies.
