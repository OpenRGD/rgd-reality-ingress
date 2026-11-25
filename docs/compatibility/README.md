# RI-A01 — Compatibility Registry v0.1

**Candidate engineering inventory; snapshot 2026-11-25. Not a canonical contract or an authorization service.**

The [master issue #6](https://github.com/OpenRGD/rgd-reality-ingress/issues/6) is the mutable coordination checklist. This directory holds a versioned, reviewable **snapshot** of the exact tested revisions and their evidence scopes. It is not a device registry, module installer, service discovery, identity/ACL resolver, evidence store or History writer. Never consume the registry as runtime authorization, consent, source attestation or a declaration of installed/live hardware.

## Files and semantics

- `registry.v0.1.json`: ten original handoff targets, returned owner PRs and commit pins, selected artifact Git blob SHA-1s, linked return comments and CI runs at the exact tested head. Open gates refer to the master issue.
- `registry.v0.1.schema.json`: strictly bounded local engineering manifest schema; does NOT replace the RI consumer schema.
- `scripts/check_compat_registry.py` (repository root): validates the manifest and local frozen files. In CI the immutable Git baseline is checked too. No HTTP requests or external repository credentials are needed.

At this snapshot **7/10 targets have returned**: IMU/PERIPH/Console, Voice, Calibration, Cognition, Visual, Pulse and Core. Three await action/return: cameras, Perception (repository pending), Chronograf. The nine integration entries include three records for RI-H02, not three separate targets. All PRs listed remain draft as reviewed. No RI physical commissioning is certified.

Evidence classes deliberately differ:

| Kind | Meaning |
|---|---|
| pinned_ri_implementation | Owner CI exercised actual RI implementation at the frozen PR #4 revision. Still synthetic/offline. |
| pinned_contract_fixture | Owner tested its adapter/fixtures against the candidate contract; does not imply the RI store ran in that CI. |
| pinned_contract_boundary | Owner tested that its report is NOT a RI observation or authority. |
| metadata_only | Voice-local report/schema tests; no RI audio ingest or RI store. |
| documentary_review | Owner boundary review only; no new implementation or conformance test. |

Each linked run is a historical result observed for that exact commit, not a live status indicator. A later green run cannot overwrite an earlier failed run. Console #21's Foundation failure and #22's candidate repair are separate evidence records. Counts and detailed negatives remain in the linked owner handoffs. Core's 22 characterization cases establish a legacy camera envelope integrity gap to address in RI-A05; they do not imply that the gap is fixed. A local hash does not verify source identity, consent, freshness, history or physical truth.

## Frozen baseline and change policy

RI PR #4 head `5372f758df79c93fc887f3858d878635447f4a4d`, exact consumer schema Git blob `3d92e074e71593bf6db0a735394c628ea131668d`. The manifest inventories the original Python modules, tests, package metadata and consumer schema from that commit; all existing bytes are protected in this wave. Git blob SHA-1 here is a repository identity/drift check, not a security attestation. The legacy archive remains untouched. New additive files are permitted; modifying frozen files requires an explicit new reviewed compatibility baseline, not quietly repinning v0.1.

For changes: record the return comment and exact owner PR/commit, verify actual artifact blob and CI run head/result, classify the test scope honestly, record open gates and re-run affected owner conformance suites against the proposed new RI revision before changing a consumer pin. Keep prior snapshot/evidence auditable. A CI pass for this registry validates shape, references, coherence and local pins, not remote tests; no private Paky repository is checked out by public RI CI. Obtain owner-side rerun evidence separately. A schema/reference change needs a new explicit version and owner review. Never auto-merge, activate hardware, grant permissions or create Chronons based on this manifest.

## Offline validation

From repository root, in an isolated Python environment:

```sh
python -m pip install jsonschema==4.23.0
python scripts/check_compat_registry.py --git-baseline
python -m unittest discover -s tests_registry -v
```

The Git baseline check needs the frozen commit available locally (CI fetches full history); the normal checker without that flag still compares the local frozen file bytes against manifest pins. External tests remain in their owners' repositories. No audio, camera, sensor, device credentials or private payloads are stored here.
