# RI-A06 — Freshness, Time & Replay v0.1 candidate

**27 November 2026 · stored evidence only · non-normative · non-actuating.** Stacked on RI-A05 #12. All original files, observation IDs, owner pins and candidate reference schema remain unchanged. No acquisition or live delivery path is added.

## Ownership and evidence

RI preserves the original producer receipt. [Frozen timebase](../src/reality_ingress/timebase.py) records a host monotonic value and wall-clock pair estimate/span; neither measures exposure, sensor latch or cross-host uncertainty. A03 preserves original source sample bytes and does not restamp at import. A04 provides separate authorized-style metadata and bounded original IMU payload views. A05 checks exact selected content separately; its checkpoint is not a capture or time attestation.

The Chronograf reference repository was reviewed at [80dc9cc](https://github.com/RobotChronograf/chronograf/tree/80dc9cc3dd0cf16a94a0c6b08ce4c8c5a37ae6b5); the separate runtime repository reports empty. RI-H09 remains awaiting return. No Chronograf package/code is imported or redistributed. Chronograf owns qualified TimeAtom, uncertainty and opaque AnchorRef64; Core/History owns authenticated commitments, not RI. Core-D [D-TIME-01](https://github.com/OpenRGD/openrgd/blob/7b15fda5c825f9359ce0045377ec38364de19efb/contracts/temporal-memory/v0.1.0/TEMPORAL_DELTA.md) explicitly separates historical event assertions and actual import/commit measurement.

## Five distinct time roles

| Role | A06 handling |
|---|---|
| Physical source measurement/exposure/latch | UNKNOWN, null; never infer from receipt |
| Original publisher userspace receipt | Exact original monotonic ns, clock-domain/boot labels; original wall estimate, span and method only when present in checked source-owned payload |
| Import operation | Optional separate host-reported mark with its own clock/boot and role; null if not supplied |
| Verification operation | Optional separate host-reported mark with its own clock/boot and role; null if not supplied |
| Temporal assessment | Current configured local monotonic reading at assessment start; not time of acquisition, import, verification or History commit |

Host operation marks are external claims, not proof of operation completion or measured Chronograf time. This wave does not instrument A03/A05 or synthesize missing past marks. Same-local-context future operation marks are rejected; unrelated clock values are never subtracted. The wall-pair span is not end-to-end latency or source uncertainty. No restamping, clock correction, arbitrary anchor or History receipt. All timestamps remain exact native u64 values; separate transport review needed before JavaScript binary64 conversion.

## Local assessment and clock relationship

New optional `TemporalReview` in `src/reality_ingress/temporal_review.py` accepts already authorized A04 results in a trusted host process, no filesystem/network lookup. Only its owner object can invoke it; this is not authentication or proof that a cached AccessResult remains authorized. Host must obtain a current view and check external consent/retention before any review or downstream release; no new grant is minted. Blocked/unavailable views produce no report. Metadata-only IMU/RGB references retain original receipt labels but no session, method or inferred age. Checked original bounded IMU bytes are revalidated with A03/A02 and the frozen projection; unsupported media and Voice segment-close reports are not accepted as observations.

Host supplies `HostClock(host_label, clock_domain_id, boot_id)` and, optionally, a `PublisherClockClaim` for exact original source/frame/modality/session/clock. Same boot/domain text alone is insufficient. Only a claim matching the checked source scope and assessment host/boot/domain permits conditional receipt-age arithmetic. Host labels and clock assertions are not authenticated. Compare original receipt to assessment clock only when aligned; future receipt fails closed. Missing or mismatching claims, different host, different boot/domain, unresolved session, camera metadata-only -> receipt age null/UNKNOWN. No implicit cross-host mapping.

`receipt_age_state` is RECENT_RECEIPT when age < the configured threshold, STALE_RECEIPT when age >= threshold, otherwise UNKNOWN. Default threshold 3s, configurable up to 60s in exact integer ns. Not the existing Console/Pulse TTL policy. Local clock invalidity/regression closes the reviewer. Source measurement freshness remains UNKNOWN, source time uncertainty null, Chronograf UNRESOLVED, all authority false.

**Every view is stored evidence.** Presentation is explicitly ARCHIVE_READ (default), IMPORT, REIMPORT, REPLAY, SYNTHETIC, or UNKNOWN, an external host label, not proof of provenance or verified import/replay operation. There is intentionally NO LIVE mode: even a RECENT_RECEIPT after import/replay is not fresh physical sensing. Neither integrity, reimport, reading, later assessment nor synthetic replay can turn this into a new live observation. A separate approved live profile would require real acquisition owner and clocks.

## Bounded duplicate/replay discipline

One local in-memory ledger per trusted host review session, maximum 64 distinct observations (lower configurable). No eviction or auto reset. Stable original observation ID and digest of canonical projected reference with only integrity_status normalized to not_verified for internal comparison; this is not a new identifier, signature, acceptance of an updated reference, or source authentication. Different content for same ID -> collision. Validate payload and temporal context before duplicate handling. Repeat same ID -> DUPLICATE with no new report or refreshed timestamp. Metadata→checked payload may add the newly checked key internally, but emits no second assessment and does not retroactively qualify earlier clock claims.

Track source/modality/frame/session/sequence/domain/boot labels from A02-validated source content. Same claimed sequence key with different content -> collision. Separate boot/session scopes; historical out-of-order sequence is labelled, not live or necessarily tampered. Numeric receipt ordering between records is compared only if both had explicit aligned same-local-clock assertions. No numeric comparison from labels alone. Conflicting receipt/sequence order in aligned scope rejected. No global, durable, cryptographic replay ledger; a fresh process lacks history and does not authorize a replay. Backpressure fails closed; no caller can use a reset to obtain live authority.

## Additive report and compatibility

`contracts/temporal-assessment.v0.1-candidate.schema.json` is a separate closed report. Exact u64 integer bounds, conditional unknown age, null source/Chronograf fields and false authority. Schema alone does not validate arithmetic, clock claims, replay identity or actual authorization. Runtime checks remain separate. Never send this report as an ObservationRef, COG InputEvent, proposal, HistoryCommitRequest, Chronon or an attested physical time. Report carries only authorized metadata, not original payload/path; do not log or disclose it without independent permission.

COG #8 in #9 still computes FRESH for same-boot trusted receipt, even on a historical view if configured that way. This is a characterized compatibility gap, not a claim that COG can classify historical presentations today. For stored references in the existing candidate, do not enable same_boot_clock_trusted on the basis of RI-A06; use conservative UNKNOWN or withhold until owner approval. Its metadata→checked-view collision guard stays intact. A06's internal normalized fingerprint never changes COG's acceptance or replay cache. Future owner review of separately authorized temporal/status sidecars is needed before downstream use. Console numeric matching, PERIPH/Pulse TTLs, CAL sidecar, Voice capture/close clock, C1 and Work remain unchanged.

## API (trusted offline host; no deployment)

```python
from reality_ingress.temporal_review import TemporalReview, HostClock, PublisherClockClaim
# owner retained by trusted host; clock_context supplied independently
review = TemporalReview(owner=owner, clock=clock_context)
# view freshly obtained by host through existing A04 authorized reader
result = review.assess(owner, view, presentation="ARCHIVE_READ")
# publisher_clock optional, externally asserted exact scope; default UNKNOWN
# only result.status == "ASSESSED" carries a candidate report
```

## Remaining gates

Actual RI-H09 handoff: agree time qualification request/receipt shape, external clock-domain identity, uncertainty, clock relation and namespace/opaque anchor; do not derive anchor from receipt or backdate. A11 owns optional qualified-time/History bridge. Durable anti-replay state and host authentication/policy, A04 revocation/retention, A05 durable checkpoint/verification integration and writer coordination, true live freshness profile, A07 physical pilot remain open. No new time server, device, network, authorizations, deployment or canonical promotion.

Tests: synthetic actual A03/A04 path, missing/foreign clock, u64, past/future/stale thresholds, unchanged receipt, explicit operations, reimport/duplicate/collision/order/boot/regression, denied/unsupported data, schema/no authority. Actual pinned COG tests characterize historical receipt setting and preserve guards. Existing CI remains independent.

[Master #6](https://github.com/OpenRGD/rgd-reality-ingress/issues/6) · [RI-A05 #12](https://github.com/OpenRGD/rgd-reality-ingress/pull/12) · [COG #9](https://github.com/OpenRGD/rgd-cognition/pull/9) · [RI→Chronograf original](handoffs/RI-TO-CHRONOGRAF.md).
