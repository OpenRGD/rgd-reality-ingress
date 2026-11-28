# RI-INTEGRATION-02 — Stack Consolidation & Pilot Readiness

**28 November 2026 · review candidate · no deployment · no physical authorization.**

## Frozen review

[Stack review snapshot](integration/stack-review-2026-11-28.json) records the eight RI draft steps #4 → #7 → #8 → #9 → #10 → #11 → #12 → #13, their exact base/head commits, eight successful workflows at #13, and newly verified owner merges. The original A01 and CAL-only historical registry snapshots remain immutable. The snapshot is dated engineering evidence, not a live registry, installation report or canonical acceptance. RI-H01, H07 and H09 remain open.

The previous historical owner pins are not rewritten. Reviewed merge commits:

| Owner | Source merge | Evidence at merge / boundary |
|---|---|---|
| Paky #8 | `ca5fd652d43cdf5298ddf50470c98e0724ac5b5f` | Static no-hardware audit; producer and fixture blobs unchanged. Owner-local integrated rerun pending. |
| IMU #4 | `b8fd0b714098780792c9e16aa1b00ac3d583b037` | Foundation/01C/01D green against historical RI pin; no installed migration. Owner-local integrated rerun pending. |
| Console #22 | `b331dd32415eeda0d107676920a6dea91170cc4f` | Foundation and PERIPH green at merge; original helper/test blobs identical. This wave reruns merged helper against additive RI. |
| PERIPH #1 | `a36c2d7c42b0bb3f4b2e4c78b42b999be0fac6cd` | Standalone extraction CI green; no new runtime dependency or physical broker/publisher cutover. |
| CAL #9 | `8268a621dc2b14a22473830f19d448f32236d9b1` | Post-merge owner workflows green, prior native-exchange blobs identical. This wave reruns the merged Rust test exporter, not live camera/depth. |

No RI merge or repin is authorized by this document. Parent pins remain individually reviewable; do not merge stacked PRs out of dependency order or squash away commits used by external owners. The release decision and rebase/retarget strategy belong to A12. Keep the entire stack draft until review.

## Integrated offline acceptance

Use A03 completed-spool preview and explicit apply to a private isolated test store. Owner reviews original projected ref and exact A05 checkpoint, retains expected digest independently of the evidence files. Grant only the existing A04 channel for the exact observation and diagnostics purpose. The **trusted-owner-only** harness `scripts/pilot_review.py` calls A04 read, checks A05 exact selected checkpoint and matches ID/schema/payload digest and size, reauthorizes the identical ref/payload through a second A04 read, then calls A06 without a clock assertion. No bytes, reference, report or new consumer permission leaves the harness, only a summary. Denied A04, rejected/busy A05, expired/revoked policy at the second A04 read, or a changed view stops before A06. A successful review uses two authorized attempts and charges both byte releases within the trusted host; configure at least two reads and enough byte budget per review, without bypassing A04. A single-read grant deliberately cannot pass this harness. A06 emits no second report for duplicate; historical receipt remains UNKNOWN and never live.

This harness composes existing local interfaces, including the pinned reader's internal root check. It is a test/owner diagnostic, not a stable runtime API, network reader, atomic cross-component transaction, durable authorization or substitute for A04/A05. All policy mutation must be serialized by the trusted host; the store must be quiescent, legacy writers stopped, and expected checkpoints independently retained. A04's bytes are read only into that trusted process, not released to consumers. Revocation cannot recall previous copies. This is not a new store or access authority.

CI: exact stack/tree/registry drift check, local integrated synthetic cases on Python 3.10/3.12 normal/-O, actual merged Console helper/fixture (including numeric correlation, no Console boot proof), actual merged CAL Rust exporter and separate nested schemas. Parent workflows retain actual pinned COG and Core regressions. Public CI does not check out private producers, run sensors or prove operational readiness. The private owner test is separately opt-in and imports the existing synthetic exporter helpers only from an exact clean approved checkout, no private source copied into RI.

## Gate matrix

| Gate | Required before any real pilot | Status at authoring |
|---|---|---|
| G0 stack + integrated software | Exact pins, all triggered CI green, reviewed scope and limits | Candidate CI required |
| G1 private source parity | Actual pinned Paky exporter fixture -> A03/A04/A05/A06; owner-local rerun; generalized IMU separately | Pending |
| G2 operator read-only host preflight | Exact installed source/interpreter/services, actual by-path/VID:PID/baud and sole reader, Console/K3 baseline, no guessed settings | Pending |
| G3 privacy and rollback | Owner approval, explicit purpose/retention and local isolated private paths, restore exact existing invocation, non-actuating safe state | Pending |
| G4 finite IMU test | Explicit separately approved 30s existing source owner only; no automatic launch; evidence and fail-soft/stop parity | NOT AUTHORIZED |
| G5 post-pilot review | Offline complete spool, import and exact correlation, checkpoint/replay and failure evidence; owner acceptance, no deployment | Pending |

CI cannot turn G2–G5 green. If any gate is not confirmed, do not start an acquisition. A07 remains open. Camera, audio, continuous acquisition, generalized publisher migration and live COG/Chronograf/History are excluded from the first pilot. No CAN, motors, calibration commands, BLE or new device access.

## Owner-local software rehearsal

Use a new detached checkout of the reviewed RI consolidation commit and a new isolated Python environment, not the installed robot runtime. First run:

```sh
python -m pip install -e . "jsonschema==4.23.0"
python scripts/check_integration_stack.py
python scripts/check_compat_registry.py --git-baseline
python -m unittest discover -s tests_integration -v
```

For G1, use a clean, separately authorized private Paky checkout at the merge pin above, with the owner's ordinary synthetic-test dependencies installed in the isolated venv. Set `PILOT_PRODUCER_CHECKOUT` to its absolute directory. From the RI root:

```sh
PILOT_PRODUCER_KIND=paky PYTHONPATH=src \
  python -m unittest discover -s tests_integration_owner -v
```

The environment variable for the checkout must already be exported. For the later generalized candidate, use the IMU merge pin, its owner test dependencies and `PILOT_PRODUCER_KIND=imu`. Do not use real spool data in these synthetic tests. These tests do not authorize actual producer execution on a device, use fake/synthetic samples and private temporary directories only. Report PASS/FAIL and exact commit locally; do not upload private contents. No automatic private checkout in public workflow.

## G2 — Paky-01 read-only preflight (operator, on actual Ubuntu host)

First physical baseline is the existing Paky #8 producer, **not** the new IMU package or autonomous PERIPH installation. Follow the [owner pilot](https://github.com/italiarobotica/paky-01/blob/ca5fd652d43cdf5298ddf50470c98e0724ac5b5f/docs/IMU-RI-01-PILOT.md) and [generalized migration plan](https://github.com/OpenRGD/rgd-imu/blob/b8fd0b714098780792c9e16aa1b00ac3d583b037/docs/RI-MIGRATION-01D.md); A03 replaces the example legacy unbounded ingest for this experiment, not the installed CLI.

Use the already reviewed [Console read-only preflight script](https://github.com/OpenRGD/rgd-console/blob/b331dd32415eeda0d107676920a6dea91170cc4f/scripts/peripheral-host-preflight.sh) (blob 123b68df4a339a40b4bbbbf2dd2a18a615aa9c34). Inspect the file/hash and set CONSOLE_SOURCE_DIR and PAKY_SOURCE_DIR to the actual verified local paths first. Run the reviewed script locally, without sudo, only on the correct host. It performs metadata/status and loopback GET checks, not serial opens or service commands. Redact host paths, serial numbers, boot IDs, tokens, private values and raw logs before sharing; report status/counts, exact source revisions and whether checks passed. The script's pgrep of the old publisher is not proof of exclusivity: owner must independently verify the actual endpoint's open handles (read-only OS inspection; no device open), existing broker/units, current source owner and rollback command. If unavailable, record UNKNOWN and stop. A null/stale GET is not a failure of RI, and absence of a detected process is not proof of no owner. Verify current package and actual running version separately from checkout. No new systemd unit, restart, USB/CAN opening, installation, token readout, Docker/Compose change or automatic activation.

G2 report checklist (operator records locally):
- actual installed Console/API version and source commit; status of Console services; GET IMU null/record and K3 state before any action;
- existing publisher executable/venv and source revision, declared source/sensor/frame and session support; exact device by-path, USB identity and baud reviewed, sole owner confirmed; no second reader;
- whether legacy publisher is already managed/continuous; restore exact original invocation **without** export and ability to safely stop/restore under operator control; no service configuration mutation;
- private spool/store and separately controlled checkpoint record outside Git, enough free disk and explicit approved retention/disposal plan, no secrets in logs; current actor authorization;
- non-actuating safe configuration, explicit operator decision whether a finite test may be attempted. Any unknown or mismatch -> NO-GO.

## G3–G5 — proposed pilot sequence, not executable authorization

Only after G0–G3 and explicit owner confirmation, use the existing single owner in a finite 30s controlled session, keeping exact verified interpreter/port/baud/token mode/endpoint/identity. Operator must stop an existing reader intentionally before any replacement invocation and verify it has closed; never run alongside a managed continuous reader. Compare a finite export-off baseline to the same finite export-on invocation; use only the existing optional bounded source-owner flag (no `--continuous` or dry-run export). Use a private new/empty directory, never an automatic watch; no credential duplication. Do not take any action until separately approved by operator. Keep a non-actuating safe state. On busy/disconnected owner, unexpected source/session, new delivery failures, rate/timing regression, invalid clock, unexpected scope, or unsafe state, abort; restore exact previous command and verify Console/Pulse behavior. Do not open another reader to troubleshoot.

Compare existing authorized Console accepted counts/sequence/session, Pulse LIVE→STALE and export result (enqueued, written, dropped, skipped, errors); compare baseline accepted delivery/rate/timing and explicitly agree thresholds before physical run. Do not infer all 30s samples must exist or that every accepted sample is exported. At most 1Hz/60 sample; 8 queue slots; 4KiB row/256KiB spool. Only actual report COMPLETED, exact final name/count, no .part, plus successful independently reviewed live baseline eligible. FAILED/EMPTY/WRITER_TIMEOUT -> no ingest; even final .jsonl without confirmed completion ineligible. Do not manipulate files to pass gate.

Offline, operator independently defines SourceScope from approved source and verified original boot/session (do not infer identity solely from spool). Use A03 preview and explicit same-hash apply in isolated private test store. Match legacy canonical bytes/IDs, reimport exact spool (created=0), verify selected original checkpoint and A04 permitted read, compare authorized matching Console content with actual helper (no full archive/clock/physical proof), A06 archive-only UNKNOWN, duplicate inert. Preserve confirmed prefix on PARTIAL_OR_UNCERTAIN and inspect before explicit retry of identical spool; never delete or overwrite automatically. Check no unexpected files, missing payloads or candidates orphaned; no cleanup without separate policy. Owner keeps checkpoint digest in separate protected context. Record counts, reasons and commit pins only, not payload, hash/ID lists or raw timestamps. No remote consumer, History, calibrated posture, sensor authenticity or time qualification. Preserve old invocation/rollback until separate instance migration approved.

After actual pilot, post operator report to RI master and Paky owner. Keep camera #5 separate (H01, single owner, A/B and CAL depth gate); Voice metadata only (no PCM storage); standalone PERIPH cutover and generalized IMU migration after distinct approval; COG FRESH gap and same-ID reference collision require owner review; Chronograf H09/A11 qualification pending. Any real wider deployment requires durable ACL/retention/replay, independent checkpoint trust, coordinated writers, and A12 acceptance.

[Master #6](https://github.com/OpenRGD/rgd-reality-ingress/issues/6) · [A06 #13](https://github.com/OpenRGD/rgd-reality-ingress/pull/13) · [Camera #5](https://github.com/OpenRGD/rgd-reality-ingress/issues/5).
