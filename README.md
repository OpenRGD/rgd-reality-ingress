# RGD Reality Ingress

**OpenRGD — physical and external observation acquisition, evidence preservation and provenance.**

**Status:** repository bootstrap / contract-design candidate. The original Fedora
`openrgd-reality-ingress-v0.4` implementation has been recovered on the
`recovery/ri-v0.4-fedora` branch, with 34 passing synthetic tests. It remains
**experimental and non-normative**; it is not evidence of a physically
commissioned runtime on Paky-01.

## Responsibility

Reality Ingress accepts observations from independent sources (USB cameras,
stereo frames, microphones, IMUs, robots, simulators and external providers).
It preserves *what was received* separately from any later interpretation.

An observation should carry or reference:

- source identity, independent from the robot or subject being observed;
- original payload reference and integrity commitment;
- provenance: physical/simulated/derived origin, acquisition conditions;
- source, receipt and clock-domain information without inventing synchronization;
- calibration identifier and maturity where geometrical transformations rely on it;
- stable observation identity, deduplication scope and explicit error/quality state.

## Never do

- Do **not** call object detection, classify objects or infer metric depth as the
  authoritative function of this repository.
- Do **not** turn unverified source metadata into a verified physical observation.
- Do **not** assign `SELF` just because a camera sees a robot.
- Do **not** rewrite an original observation after a newer model interprets it.
- Do **not** directly operate CAN, actuators, emergency stop or other motion paths.
- Do **not** declare Chronograf / Chronon integration operational until tested.

## Complementary module

[RGD Perception](https://github.com/OpenRGD/rgd-perception) (repository to be
created) consumes observation references and produces **derived** outputs,
e.g. object detections, stereo disparity, depth, tracks or transcriptions.
Every derived result MUST be traceable to its input observation(s), algorithm
identity/version, parameters and calibration.

The future `rgd-perception` module may run on Paky-01 or on an external RTX 5080
node. Ingress and the robot's control/safety boundaries remain local.

## Planned import process

1. Preserve the Fedora v0.1–v0.4 archives and compute SHA-256 digests.
2. Inspect the **actual v0.4 source**, tests, dependencies and generated files.
3. Exclude recorded audio/video and other personal evidence, credentials,
   conda environments, caches, datasets and all runtime state.
4. Separate algorithms from evidence acquisition *without silently changing
   v0.4 serialization or immutable identity semantics*.
5. Import with provenance, run tests, then add an explicit versioned interface.
6. Add OCCHI stereo as a source with raw paired evidence and **experimental**
   calibration metadata; do not claim certified metric depth.

## Canonical boundary

OpenRGD canonical standard:
https://github.com/OpenRGD/openrgd

The temporal model distinguishes Chronograf's time authority from Chronon
history and memory projections. Reality Ingress supplies observations and
provenance; the owning temporal and history components decide their canonical
representations. Design proposals here are not authoritative standards.

**This repository is not an actuating runtime.**

## License and publication

This repository is an **OpenRGD open-source project under the MIT License**.
See [LICENSE](LICENSE) (copyright © 2026 OpenRGD contributors).

The repository is intended to be **public**. Publishing a repository and
licensing original code are distinct from validating recovered legacy code:
Fedora v0.4 source is not in `main` and must pass attribution, dependency,
secret/PII and provenance review before import or public release. Preserve
third-party licenses and notices; MIT applies only to code we have the right
to license. Capture data, credentials and private robot evidence are excluded.

## RI-INTEGRATION-01 — Consumer boundary (candidate)

The Fedora v0.4 source is preserved on `main` after recovery PR #2. It is a historical, experimental, non-actuating baseline (34 original synthetic tests), not a deployed acquisition runtime.

The new design-only pipeline and review gates are in [docs/RI-INTEGRATION-01-PIPELINE.md](docs/RI-INTEGRATION-01-PIPELINE.md). The [cross-repository handoff pack](docs/handoffs/README.md) contains ten copy-ready, owner-specific briefs for Paky-01, Console/PERIPH/IMU, Voice, Calibration, Cognition, Visual, Pulse/Chronoscope, Chronograf, Core/History and future Perception. A strictly bounded read-only [candidate observation reference](contracts/consumer-observation-ref.v0.1-candidate.schema.json) and [pure Python adapter](src/reality_ingress/consumer_ref.py) expose v0.4 observation metadata without rewriting source IDs/hashes, claiming physical provenance/Chronograf time or granting motor authority.

**Important:** Voice/IMU/Visual Feedback and host Peripheral Manager remain independently owned systems. Their candidate contracts and physical access are not implemented by this PR; a microphone or serial device must never be opened concurrently by Ingress. Experimental YOLO and ArUco functionality remains in v0.4 for compatibility, pending the separate Perception extraction and license review.
