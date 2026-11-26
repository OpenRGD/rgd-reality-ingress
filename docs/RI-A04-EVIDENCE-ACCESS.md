# RI-A04 — Evidence Access & Availability v0.1

**26 November 2026 · local offline candidate · non-normative · no deployment.** Stacked on RI-A03 #10; previous files, IDs, schemas, compatibility snapshots and commits unchanged.

## Decision and first scope

A reference is an identifier, never an access token. Access decisions, evidence availability, content integrity, physical identity and historical authority are distinct.

This wave implements a bounded **local in-process reader**, not a service or vault. The host exclusively owns the reader instance, the opaque owner channel, external authentication and actual consent decisions. Only that owner can register an exact reference scope and issue opaque local reader channels. Caller-supplied booleans, an ObservationRef, a producer report or a JSON object do not mint a grant. The trusted host must authorize the caller independently before distributing a channel; same-process Python introspection or direct legacy filesystem access is NOT isolated by this implementation.

The supported scope is existing stored IMU generic references and legacy RGB/JPEG camera **metadata**. Payload reads support only the two original bounded source-owned IMU profiles reviewed in RI-A03; audio, camera media, arbitrary generic payloads, normalized COG-copy profiles, Voice reports and derived sidecars are not admitted for payload release. No capture or persistence is enabled. The reader reuses A03 profile validation and A02 content matching; no independent acquisition, store or identity resolver.

## Independent policy dimensions

| Scope | Rule |
|---|---|
| Observation | exact owner-pinned projected reference, observation ID and digest; fixed private store root |
| Purpose | explicit operator_review, diagnostics, calibration, cognition, perception; no remote upload purpose |
| Consent | metadata default false; payload separately default false; payload requires metadata |
| Grant | local opaque channel, exact observation/purpose, metadata or payload, monotonic expiry, revoked/closed |
| Retention | owner-set local access deadline, caps every grant, cannot extend/re-register in the same reader |
| Withholding | one-way local RESTRICTED / REDACTED / ERASURE_REPORTED for metadata or payload; metadata withholding also blocks payload |
| Availability | assess only data actually inspected; no inference from policy, hash or mere file name |

Default deny. Unknown channel, wrong ID/purpose, ungranted scope, revoked channel: same response, no file lookup, no ID/hash/path in result. An already scoped caller may receive a bounded reason for its expired, withheld, missing or corrupt evidence. Metadata withholding denies both scopes; payload withholding does not implicitly erase separately authorized metadata. No replacement redacted copy is manufactured. No report asserts verified erasure.

### Explicit local limits

At most 64 registered evidence policies and 64 total channels per reader instance (including revoked channels); 60 authorized read attempts per grant, default 1. Each metadata read is bounded by 64 KiB envelope / 16 KiB projected reference. Payload ceiling 4096 B, per-grant total released payload ceiling 256 KiB; both may be lowered. No store enumeration. Maximum grant TTL 3600 seconds; maximum local retention window 86400 seconds. Both are local monotonic policy limits, not sensor time or Chronograf timestamps. Unknown/regressed/failed clock closes the reader fail-closed. Check policy again before release; serialize reads and policy changes in a local lock. A revocation is effective for subsequent calls, not data already returned or a read linearized before it.

These are candidate lab budgets, not a global lifetime archive quota. **Durable** consent/retention across restarts, quota reservations at intake, deletion/backup/cache/replica lifecycle, legal/organizational consent and audit persistence require a separate reviewed host policy implementation (A04 follow-up). No reset may be used to evade policy: host must reload legitimate current decisions before a new reader is created. Current in-memory policy cannot prove durable revocation or erasure. No automatic GC, deletion, restoration, or storage change; aggregate owner-only counts, no persistent private audit log.

## Read and availability semantics

- REFERENCE_ONLY / UNKNOWN: owner-authorized metadata, projected original v0.1 fields, integrity_status=not_verified. Never open, stat or verify payload or assert availability. Existing stored envelope is not automatically an immutable verified camera metadata commitment.
- PAYLOAD_RESOLVED / AVAILABLE: actual bounded selected original generic payload read, SHA-256/size, existing reference pin, canonical envelope and A03/A02 content checked; compare envelope snapshot again. Return exact original bytes and unchanged reference shape with verified_local_hash. The new **local result** additionally labels integrity_scope=SELECTED_LOCAL_SNAPSHOT; this is not store-wide verification, source/robot attestation, calibrated data, authorized History or a stable durable receipt. RI-A05 must review the scope and stronger storage invariants before production use.
- BLOCKED: NOT_AUTHORIZED, EXPIRED, RESTRICTED, REDACTED, ERASURE_REPORTED, or UNKNOWN (reader failure). No reference or payload. Erasure reported is a policy claim, not proof of deletion. Not-authorized responses do not expose existence.
- UNAVAILABLE: MISSING, CORRUPT_OR_UNSUPPORTED, UNAVAILABLE; only for an authorized exact request, no bytes. Missing file is not erasure proof. Authorized failed attempts consume read budget; only actual returned payload bytes consume release budget.

Do not forward local result as a Core-D EvidenceAvailability record. COG currently supports UNKNOWN, AVAILABLE, UNAVAILABLE, REDACTED, ERASED, NOT_AUTHORIZED; successful metadata/payload views map to UNKNOWN/AVAILABLE without schema change. Do not call COG accept on blocked/missing results; do not transform ERASURE_REPORTED into ERASED or UNKNOWN into AVAILABLE. Future owner crosswalk must handle other states. Pulse/Console status is not historical proof.

## Consumer compatibility caveat (requires COG review)

COG #8 pins the complete reference fingerprint, including integrity_status. Receiving metadata with not_verified, then the same ID with verified_local_hash in the same COG consumer instance currently triggers OBSERVATION_ID_COLLISION. That is an existing guard, not a reason to silently overwrite the record or weaken replay protection. Use the appropriate initial authorized view in synthetic tests; a future explicit owner-approved evidence-status transition/sidecar is required for upgrading an already consumed view. COG #9 normalized Console-copy remains a separate proposed representation, not an A03/A04 source profile. Console #22's original numeric correlation helper accepts the exact checked-payload projection. CAL can consume the metadata reference independently of payload, maintaining its own sidecar validation and metric-depth gate. No consumer is repinned or deployed.

## Storage and trust boundary

Only open existing canonical absolute local owner directories (0700, same UID); regular 0600 files, no symlink/hardlink/FIFO, bounded reads and file stat checks via existing A03 primitives. Construct paths solely from strict observation ID/digest, never a caller path or arbitrary envelope payload reference. Check root identity and compare selected envelope twice for the payload view. No whole-store scan or verify, no new store, write, migration or path exposed to consumer. Legacy generic metadata self-commitment checked, not equivalent to authentic source; legacy camera UUID metadata gap remains. Quiescent private store and trusted host are required, not a hostile-filesystem or multiwriter transactional guarantee. A05 owns stable scoped integrity, concurrent writer review and immutable commitments, including legacy camera metadata. A06 owns clock/freshness/replay. No time anchors or history writes here.

## API example (synthetic/local, not deployment)

```python
from reality_ingress.evidence_access import LocalEvidenceReader
owner = object()  # kept by trusted host, never exposed to consumer
reader = LocalEvidenceReader(existing_private_store_path, owner=owner)
# Host has independently reviewed this exact reference, purpose and consent.
reader.register_evidence(owner, approved_reference_bytes,
    purposes=frozenset({"diagnostics"}), retention_seconds=60,
    metadata_consent=True, payload_consent=False)
channel = reader.grant(owner, observation_id, purpose="diagnostics", ttl_seconds=10)
result = reader.read(channel, observation_id, purpose="diagnostics")
reader.revoke(owner, channel)
```

No grant is derived from actual user speech, COG reasoning or data fields. The owner of a real deployment must supply actual authentication, effective consent, retention policies and controlled transport. No real API/service or client integration was installed.

## Review/test gates

Synthetic local tests use real A03 intake and frozen store. Negative cases cover denied IO, grant/purpose/scope, no payload access for metadata, TTL and expiry mid-read, local clock regression, revocation, withholding, missing/corruption, budget, file restrictions and read-only behavior. Public cross-owner tests exercise actual pinned Console #22 and COG #8 implementation in #9, including the fingerprint transition limitation. No hardware, private producer, real consent, CAL media, archive quota or global integrity test claimed. Existing A01/A02/A03/native-u64 regressions unchanged. A04 follow-up and A05 gates remain before live use. No merge, deployment, new permissions or standard promotion.

[Master #6](https://github.com/OpenRGD/rgd-reality-ingress/issues/6) · [A03 #10](https://github.com/OpenRGD/rgd-reality-ingress/pull/10) · [COG #9](https://github.com/OpenRGD/rgd-cognition/pull/9) · [Console #22](https://github.com/OpenRGD/rgd-console/pull/22).
