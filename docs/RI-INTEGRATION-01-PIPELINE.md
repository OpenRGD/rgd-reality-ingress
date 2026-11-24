# RI-INTEGRATION-01 — Reality Ingress multimodal pipeline & owner boundaries

**23 Nov 2026 · design / integration candidate · non-normative · non-actuating.**

**Baseline:** Fedora Reality Ingress v0.4 is on `main` after PR #2, with 34 passing synthetic tests and preserved provenance. This document is an *additional candidate design*, **not** an implemented shared publisher, production API, Chronograf connector or certified physical observation system.

**Handoff per tutte le altre chat/repository:** [docs/handoffs/README.md](handoffs/README.md).

## Decision

Reality Ingress is the **evidence boundary**, not a universal USB-device opener, semantic model, memory writer, attention planner or feedback dispatcher.

```text
Physical sensors / external providers / simulated sources
         │
Peripheral Manager (candidate control plane) + ONE host acquisition owner per resource
         │ bounded, authenticated subscriber path; no second device open
         ├──────────────► live status (Console / operator; not historical truth)
         ▼
Reality Ingress (validation, provenance, integrity, optional LOCAL evidence store, not canonical L1 vault)
         ├──────────────► read-only evidence refs & freshness (Console)
         ├──────────────► Perception / stereo / visual derived processors (Voice retains VAD/STT ownership)
         ├──────────────► optional qualified temporal assertion to Chronograf
         └──────────────► optional authorised History/Evidence Vault consumer
                                  │
PerceptionResult (derived, evidence-linked, quality/uncertainty) ─► Cognition / Attention
                                  │                             └► Console
                                  └► semantic response intent ─► Voice / Visual Feedback

Independent outputs: Voice playback and Visual renderer / LED delivery.
Independent privileged boundary: Somatic safety gates (NO ingress or perception actuation).
```

The arrows are **ownership and data flow**, not evidence that these interfaces are deployed. Console may subscribe directly to an existing publisher for fresh telemetry; Ingress must not replace a working publisher or silently interpose on a real-time control path.

## Ownership for Paky-01 (current vs target)

| Source/service | Current grounded implementation | Reality Ingress role | Must NOT do |
|---|---|---|---|
| OCCHI 3D stereo UVC, VID:PID 32e4:2b10 | 2560x720 SBS MJPEG at 30fps tested; v0.4 camera adapter is an experimental *single camera opener* | One authorized host camera publisher may reuse that adapter and emit hashed observations. Preserve A/B stream order and calibration ref. | Duplicate V4L2 opens, claim synchronized exposure or certified depth |
| Logitech C920 | UVC live capture tested, physical external view | Separate camera source / stable UID, reference frame and independent session | Treat an externally observed robot as `SELF` |
| BC-Master USB & body mic | Voice v0.3.1 and PulseAudio/parecord own speech acquisition in legacy pilot; PERIPH audio owner is proposed (Voice PR #3) | **Only** subscribe to consented frames/segments/refs from the one audio owner; minimal retention | Open the same microphone again, continuously archive ambient conversations |
| WIT/CH340 torso IMU | Paky-01 host publisher → token-protected loopback Console endpoint → read-only WS (Console IMU v0.5 candidate) | Consume a source-authored sample via reviewed fan-out/bridge, preserving native clock, sequence, sensor axes and quality | Open a second serial port, synthesize torso-calibrated/world-frame pose, assume an IMU estimate authorizes movement |
| Peripheral Manager | Console PR #5/#6 propose device/publisher/stream status and host broker; **not yet live for cameras/audio** | Respect resource leases and source presence. No competing discovery/start-stop control plane | Treat process running as proof of live frames, use generic shell control |
| Voice (listening/thinking/speaking) | Voice lifecycle schema and candidate Voice→Visual relay | A lifecycle event is **producer-reported activity**, not raw sensed speech; may reference consented evidence | Claim successful playback is an acoustically observed sound |
| Visual Feedback / eyes / ring | Owns output scene/device adapter; Core feedback PR #6 is candidate | Optionally record independently supplied output-delivery reports as reports, with stated proof limits | Interpret a BLE write as observed photons, decide expressions |
| Chronoscope/Pulse Pico W | Hardware/UI for temporal/status presentation | Consumer of *qualified* temporal or status data if wired; no inherent global time authority | Invent a Chronograf TimeAtom or anchor from a device clock/display |
| Chronograf / Chronon / Memory | Separate temporal & History owners; Core-D PR #14 remains non-normative | Preserve timestamp assertions; future bridge may request verified Chronograf anchor/History commit from the authority | Assign canonical life history, memory, identity, or Chronon IDs on its own |
| Cognition (COG C0/C1/Core-B) | Session-scoped non-actuating proposals & attention, separate draft stacks | Supplies evidence refs, observation quality, freshness; optional derived Perception | Decide goals, own attention, issue effect grants or motion |

**NOTE:** Device identity, `source_id`, robot instance binding, Life binding, frame calibration and human/robot subject identity are different claims. Until separately verified, explicit `unverified`/null semantics apply.

## Four data classes: NEVER conflate

1. **Source observation:** a camera JPEG reconstructed from decoded pixels, audio segment, received IMU sample or structured external telemetry with source, bytes/hash, host receipt-clock evidence and unknown source exposure/latch time when unavailable. Source verification/physical origin claims are independently qualified.
2. **Derived interpretation:** YOLO label, ArUco detection, stereo disparity/depth, speech transcript, sensor-fusion result. It MUST reference *immutable observed input(s)* and processor/model/config/calibration identity, plus quality/uncertainty. A derived result is not an overwrite of an observation.
3. **Producer lifecycle/delivery report:** Voice `speaking`, an IPC acknowledgement or LED adapter `applied`. It says what a producer or driver reported, **not** that sound/light was physically sensed; use a distinct event/report type.
4. **Cognitive or proposed effect:** attention/goal/response/intent/decision. Its provenance is cognitive, NOT a physical measurement or safety grant. Only independent effect authority can consider execution requests.

Synthetic input, hallucinated interpretations, replay, imports and reprocessed historical data are explicitly identified. A dashboard must never display them as fresh verified physical observations.

## Producer/consumer contract: minimal candidate

`contracts/consumer-observation-ref.v0.1-candidate.schema.json` defines **a compact, read-only pointer** for explicit consumers. It is not the historical v0.4 `ObservationEnvelope`, does not alter existing IDs/hashes, and must not become the canonical Core schema without review.

A producer that **actually validated local evidence integrity** may publish a reference containing:

- exact `observation_id`, `source_id`, `modality` and source-frame ID;
- payload hash, media type and size, but **never raw local filesystem paths to untrusted remote clients**;
- source clock domain/boot and host monotonic *receipt*; source-latch/exposure timestamp remains unknown until verified;
- `integrity_status` as either `verified_local_hash` or `not_verified`, not a cryptographic signer identity;
- verification flags **false** and `history_status=not_committed` for the current legacy bridge.

Consumers resolve IDs with access controls and compare hashes through an authorized evidence store. They must handle missing/expired/retained-but-restricted payloads; reference publication does not grant media access. The notice is NOT a Chronon, enrollment credential, actual capture frame time or permission to move.

### Backwards compatibility

Legacy v0.4 has two related observation formats: camera `observation-envelope:v0` UUID-like IDs and generic `generic-observation:v0` content-addressed IDs. Do not re-key or rewrite them. Legacy camera evidence may be **decoded and re-encoded JPEG**, not the original USB MJPEG transport bytes. Preserve its exact `provenance.derivation_str`. Generic JSONL sources preserve original source-stamped receipt metadata and must not be restamped on import.

Also preserve v0.4's `EvidenceStore.verify()`, idempotent JSONL ingest, existing `verify`, `capture`, `derive`, `markers-*` CLI functions during an explicit compatibility period. Perception extraction into `OpenRGD/rgd-perception` is a **separate** licensed/reviewed change, not a silent deletion of legacy behavior.

## Temporal and history boundary

- Record `received_monotonic_ns` along with the **same boot clock domain** and separately identified wall-clock estimate. Never infer camera exposure time, physical simultaneity or cross-host ordering from the receipt timestamp.
- Chronograf qualifies time/uncertainty/anchor **in its own independent component**. Chronoscope/Pulse displaying a time does not certify Chronograf binding.
- Core-D is a **candidate**: L0 volatile samples and protected L1 evidence vault are not themselves L2 canonical Chronon history; history commits require independently authorized Life/writer/effect proof. Do not automatically persist every sensor frame to canonical history.
- Indeterminate history-write acknowledgements must not be treated as `COMMITTED`. No retroactive timestamp promotion.
- If no time-domain synchronization is evidenced, cross-host association is `UNKNOWN`, not `SIMULTANEOUS`.

## Privacy, capacity and safety rules

- **Privacy:** do not retain ambient microphone audio by default. A clearly bounded purpose, positive authorization, local retention/expiry and access-controlled media refs are mandatory before persistence or remote transmission. Face/voice data are sensitive and should stay out of Git.
- **Bounded backpressure:** live 30fps stereo is NOT an instruction to hash/archive every frame. Use explicit sampling, queue size, size quotas, loss counters, drop policy and observable freshness; preserve causal gap information. No blocking the audio capture thread, IMU sensor reader or Somatic loops for persistence.
- **Remote RTX 5080:** send only policy-approved derived inputs or selected image/audio references over authenticated encrypted private transport; remote provider can never be a single point of failure for local acquisition/safety.
- **Evidence integrity:** SHA-256 is content consistency, not source authentication, user consent, metrological calibration or trusted temporal provenance.
- **Somatic:** no CAN/servo/socket action channels, arbitrary shell commands, e-stop/balance claims, or privilege elevation from Ingress or Perception.
- **Licensing:** MIT for OpenRGD-owned Ingress code; legacy optional Ultralytics inference uses separate license/compliance review before product distribution.

## Gate sequence for RI-INTEGRATION-01

**Gate A — completed:** Fedora v0.4 historical source (PR #2), hash/provenance, 34 synthetic tests, MIT and docs-integrity CI, merged to `main`.

**Gate B — candidate (this PR):** settle read-only reference shape, producer-specific ownership, privacy/retention, quality/clock semantics and cross-repo handoffs. Run static contract checks. **No physical daemon enabled.**

**Gate C — later:** explicit camera/publisher pilot on Paky-01 (one owner), bounded snapshot evidence and external consumer; cross-verify IDs, hash, no duplicated USB open, stale/disconnect, rollback. IMU/Voice subscribe via existing producers only after their reviewed adapters exist.

**Gate D — later:** Perception derivation separation, non-actuating COG context adapter and Console read-only presentation. Chronograf/History bridges need separately reviewed authority tests.

## Cross-repository handoffs

- **Voice PR #3:** publish an opt-in, consent-limited PCM/event subscription from its approved acquisition owner; avoid a second PulseAudio capture. Voice Visual lifecycle stays in Voice/Visual.
- **Console PERIPH PRs #5/#6:** adopt device/publisher/stream status vocabulary and exclusive owner/lease; no claims that camera/microphone broker is implemented.
- **IMU Console v0.5:** do not create another serial reader; adapt existing host publisher output without changing its token or live WS semantics.
- **Calibration PR #4:** OCCHI 35-pair experimental profile must remain `candidate`; do not infer physically verified 3D distances or lens order A/B.
- **Core-D PR #14:** negotiate temporal assertion/History commit status later, with failed/unknown state preserved; no auto-issuance of Chronons.
- **COG C1/Core-B:** accept observation refs as untrusted external evidence with quality and SESSION_SCOPED context; do not manufacture identity, selfhood or permission.
- **Visual Feedback/Core feedback PR #6:** delivery reports are output-device reports; only independently sensed light/sound would become physical output observations.
- **Chronoscope/Pulse:** consume statuses / qualified timestamps; defer cross-host synchronization until proven.

**Promotion requirements:** explicit human review, non-regressing v0.4 tests, new consumer conformance fixtures, precise privacy policy, source identity review, no concurrent owners and genuine Ubuntu hardware validation. Merging this document or schema alone does not satisfy them.
