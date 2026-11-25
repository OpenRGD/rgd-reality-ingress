# RI-A02 — Session & Binding Resolver (local candidate)

**2026-11-25. Non-normative, non-actuating, offline content correlation only.** Stacked on RI-A01 #7, with RI #4's frozen contract and code unchanged.

## Decision

A compact `ri.consumer-observation-ref.v0.1-candidate` does not contain the publisher session or an authenticated host identity. An observation identifier, payload hash, source label or same numeric sequence is not enough to bind a sample across publisher restarts.

This wave adds an isolated local Python API in `src/reality_ingress/session_binding.py`, not a new wire schema or authority. Given **immutable bytes already obtained by an independently authorized reader**, check the existing ref against the envelope, recompute exact payload SHA-256/size, decode bounded strict JSON, use the original generic v0.4 validator/canonicalization, reconstruct its original envelope including its observation ID, and compare exact canonical content. Only explicit `source.session_id_str` may supply a session. The IMU source-owned wrapper's duplicated source/session/frame/sequence/receipt fields must agree.

`SessionKey` is a tuple of **claimed labels**: source ID, modality, frame, producer session, sequence, clock-domain ID, boot label. No host or physical identity is invented. `SessionBinding` returns only local content association metadata, no media, path or access token. `resolve_unique` checks up to 64 explicitly supplied candidates / 4 MiB total, collapses duplicate content, rejects ambiguous same-key observations and refuses a positive uniqueness claim if any supplied candidate is unresolved or invalid. This is NOT global uniqueness in a store, an anti-replay ledger, device attestation or a production index. No clock comparison between hosts; freshness UNKNOWN; source/binding/history/actuation and access/issuance/availability verification false.

## Compatibility and non-adoption

| Owner | Current contract preserved | RI-A02 boundary |
|---|---|---|
| Paky #8 | Original producer-owned generic JSONL, original receipt/session | RI accepts the already supplied stored generic content. No second reader or WS ingest. |
| Console #21/#22 | Offline correlate(console, ref, authorized payload) | Numeric/SI value and read-side matching remain with the existing helper. Console lacks boot ID; no implied same-boot verification. |
| COG #8 | Inert RI metadata notice | Existing ref unchanged, no goal or authority. |
| COG #9 | Proposed normalized Console copy profile `cog-ri-02.console-copy.v0.1-candidate` | Explicitly unresolved by RI-A02, even when a nested record contains session. Its RI-side receipt and original publisher receipt differ; do not register this as a deployed producer profile or introduce a second ingestion adapter. COG's independently tested binder remains its owner. |
| CAL | Separate sidecar, profile and revision | No new binding of A/B, geometry or device identity. |
| Voice | Volatile segment metadata | No audio intake or fake observation ref. |
| Visual / Pulse | Producer reports / independent live diagnostics | Not sensor samples or History. |
| Core #17 | Local hash ≠ full envelope integrity or authority | Legacy camera UUID envelopes are explicitly unresolved, even if payload verification succeeded. A metadata change and self-consistent ref cannot establish the original camera session. RI-A05 must handle additive integrity commitments; do not rewrite old IDs. |

No legacy schema, source, test, README, package version or RI-A01 snapshot is modified. The latest COG #9 return and CAL post-merge report are tracked in master #6 separately from the historical A01 registry. All pins remain frozen; new adoption must be explicitly reviewed.

## API

```python
from reality_ingress.session_binding import SuppliedEvidence, resolve_session, resolve_unique

# Already obtained immutable byte strings via a trusted, authorized reader:
item = SuppliedEvidence(reference_bytes, envelope_bytes, payload_bytes)
result = resolve_session(item)
# CONTENT_MATCHED means supplied bytes/labels are consistent, nothing more.
if result.status == "CONTENT_MATCHED":
    key = result.binding.key
    match = resolve_unique((item,), key)
```

This API does not itself check authorization or obtain any inputs; do not expose it as a network API or use it for unauthorized resolution. Missing data is INPUT_NOT_SUPPLIED, not proof of erasure/retention/denial. RI-A04 owns authenticated lookup, ACL/consent, availability and retention; RI-A05 owns stable store verification and race handling; RI-A06 owns replay and time qualification. Matching a ref marked `verified_local_hash` does not authenticate the ref issuer or prove current store availability. The caller must enforce the appropriate authorization outside this pure API. Return classes are local Python candidates and not credential types.

## Tests and limits

- Original v0.4 and RI #4 tests remain unchanged; RI-A01's original local Git pins and registry tests remain applicable.
- Local RI-A02 tests use the genuine legacy EvidenceStore and generic producer to exercise missing or conflicting sessions, restart/boot mismatch, duplicate and ambiguous candidates, payload/ref/envelope tampering, authority flags, path-free resolution, strict bounded JSON, proposed COG copy profile and camera metadata limitations.
- Public CI re-runs the actual pinned Console #22 and COG #9/#8 owner tests **against the additive RI checkout**, and checks the new resolver on their real synthetic fixtures. It does not re-run the private Paky #8 suite, physical hardware, full Console/COG runtimes or CAL/Visual/Voice/Pulse suites. Owner-side reruns remain necessary before any repin or adoption.
- Local and cross-repo suites are distinct; COG's successful normalized-copy binder tests do not authorize that profile inside RI.
- Rollback: stop using the new optional module; no migration, store write, daemon, hardware or token change.

## Review request to IMU / Console / COG

Review the source-owned session extraction and the explicit unresolved state for COG's alternate stored profile. Agree whether Cognition can reuse the authorized original source record/correlation from Console #22 without introducing a second ingestion representation. Do not change COG C1/Work admission, Console GET/WS, publisher clocks, or the RI v0.1 reference. Later A04 must provide a scoped reader and A05 stable verification before any production usage. A07 pilot remains operator-controlled.

[Master checklist #6](https://github.com/OpenRGD/rgd-reality-ingress/issues/6) · [RI #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4) · [RI-A01 #7](https://github.com/OpenRGD/rgd-reality-ingress/pull/7) · [Console #22](https://github.com/OpenRGD/rgd-console/pull/22) · [COG #9](https://github.com/OpenRGD/rgd-cognition/pull/9).
