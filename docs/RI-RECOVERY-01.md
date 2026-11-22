# RI-RECOVERY-01 — Fedora v0.4 recovery audit

**Status:** source imported in recovery PR #2; synthetic test CI passed (34/34). Merge/promotion remains a separate reviewed decision.
**Scope:** legacy experimental baseline, not normative Canonical Core.

## Archived evidence

- Source archive: `openrgd-reality-ingress-v0.4.zip`
- SHA-256: `4e88aef9999d8f12d57fac2b027eff58adf9a125ad1ccb2275e98e3936ffe81b`
- Package: `openrgd-reality-ingress-experimental==0.4.0`
- Archive: 23 regular files; no suspicious paths, symlinks or recognized key/token patterns in a bounded text scan
- 34 of 34 `unittest` tests passed using `PYTHONPATH=src python -m unittest discover -s tests -v`; validation performed in the audit environment (synthetic tests, not real sensors)
- No physical Paky-01 acquisition, camera timing synchronization, CAN access, Chronograf anchor or Chronon write was verified by this audit.

## Boundary reconciliation

- Retain v0.4 as a **read-only history-compatible baseline** initially.
- Ingress-owned: observation acquisition, external JSONL telemetry ingestion,
  receipt clock-domain metadata, evidence store, integrity, content address,
  idempotence, sources and provenance.
- Perception-owned (future separate repository): YOLO predictions, ArUco
  interpretation/tracking, derived semantic claims and stereo depth.
- Calibration-owned: camera intrinsics/extrinsics, candidate lifecycle;
  neither Ingress nor Perception should claim physical certification.
- Chronograf owns canonical time anchoring; RGD-Physics/Chronon history
  owns canonical history; the local v0.4 timebase is only diagnostic.
- Neither ingestion nor interpretation authorizes motor action.

## Explicit caveats

- Legacy v0.4 includes `src/reality_ingress/perception.py`,
  `fiducials.py`, `calibration.py` and `derivations.py`.
  **Do not delete or move these yet**: preserve behavior and tests, then
  extract to Perception behind versioned compatibility adapters.
- The original source ZIP contains no LICENSE file. The repository root MIT license covers only OpenRGD-owned code; third-party dependencies (notably optional Ultralytics) retain their own licensing and require independent compliance review.
- Filename/regex scans cannot prove absence of all secrets.
- Do not commit `reality-evidence*`, personal images, downloaded models,
  camera recordings, Python environments, local output or robot secrets.
- Fedora v0.4 sources are for source recovery, not a production release.

## Import plan

1. **Completed:** digest verification; allowlisted source/tests and preserved history; GitHub PR #2 with 34/34 passing CI tests.
2. **Pending:** reviewed merge to `main`; experimental candidate does not become a production or canonical runtime.
3. **Pending:** separate `OpenRGD/rgd-perception` extraction, preserving original immutable evidence IDs and historical API compatibility.
4. **Pending:** physical commissioning on Paky-01 and licensing review for optional third-party processing dependencies.

**No canonical schema promotion or actuator permission is implied.**
