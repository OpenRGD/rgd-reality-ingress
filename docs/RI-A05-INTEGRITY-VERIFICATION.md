# RI-A05 — Integrity Verification v0.1 candidate

**27 November 2026 · offline owner-side inspection · non-normative · non-actuating.** Stacked on RI-A04 #11 at `3b9a9c2e6d7f69aae3dde1e690fc3c90562a1f43`. All existing code, schemas, legacy identifiers, storage bytes, test pins and registry snapshots remain unchanged.

## Problem and decisions

The frozen v0.4 store's `verify()` scans all observation manifests and derivatives. The old `verified_ref_from_store()` then separately reads an envelope; success is not a stable snapshot and unrelated corrupt records may block a valid one. Core #17 demonstrated that a legacy camera UUID does not commit to its envelope, so changed camera metadata can pass a payload hash check. Generic records instead derive their IDs from a truncated SHA-256 of the canonical envelope and store a canonicalized source JSON sample.

A05 introduces an additive offline integrity inspection API, not a new evidence store, acquisition service, or replacement authorization reader. `verify_selected(root, observation_id)` checks exactly the selected manifest and payload. A04 retains ownership of consumer access. A05 is for a trusted store owner with separately authorized local access; it never returns raw media, an envelope, an ObservationRef, or a consumer permission. Its result may support a future A04 implementation after explicit owner review; A04 and the legacy API are not silently rewired in this wave.

### Independent checks

| Dimension | Meaning |
|---|---|
| HASH_AND_SIZE_MATCHED | Selected stored payload bytes match the referenced SHA-256 and exact length. No authenticity or availability beyond this local inspection. |
| GENERIC_CONTENT_MATCHED | Strict JSON, original canonical source sample, reconstructed envelope and original deterministic ID match; not an authenticated producer signature. |
| LEGACY_ENVELOPE_UNBOUND | Legacy camera UUID and payload alone do not protect historical metadata. No false full-envelope verification. |
| NEW_BASELINE_ONLY | A new exact-byte checkpoint of the currently inspected content, not retroactive evidence of capture truth. |
| MATCHED_SUPPLIED_CHECKPOINT | Current exact manifest bytes, payload digest/size and ID match an independently supplied checkpoint SHA-256. Trust in the expected digest is external. |

Use the new local candidate schema `contracts/integrity-checkpoint.v0.1-candidate.schema.json`. Its seven fields include exact raw envelope SHA-256 and byte length, original observation ID/schema, payload SHA-256 and byte length. Serialize with the existing deterministic `canonical_json` (UTF-8, sorted keys, compact separators); checkpoint digest is SHA-256 of those canonical checkpoint bytes. A format-only envelope rewrite changes the exact checkpoint even when generic semantic content still matches. No capture timestamp, attestation, signature, source binding, Life, Chronon or access grant is present. No persisted schema migration, auto-sealing, new ID or mutation.

The host must keep the expected checkpoint digest in an independently protected record; storing a digest next to mutable content does not prevent coordinated replacement. The current module returns the checkpoint but does not persist it or provide signing, key custody, external anchors, timestamp qualification or durable receipt. A snapshot of already altered legacy metadata is just a new baseline. Never claim that prior metadata is certified by creating this checkpoint today. Historical IDs remain intact.

## Bounded snapshot inspection

Existing absolute private store (same UID; 0700 directories and 0600 regular files, single link) only. Descriptor-relative child directories, strict ID and canonical payload addresses, no symlinks, no caller-supplied arbitrary file path. Reuse A03 bounded private-file read/stat checks and A02 strict JSON decoding. Limit manifest to 64 KiB and payload to 4 MiB (generic additionally limited to original 1,000,000 bytes); configurable downward. Two bounded reads of each selected file plus identity/stat comparisons, no scan of other observations or derivatives. Limits describe bytes per file/read, not disk reservation or archive quota. No new historical counter domain restriction.

A05 obtains a nonblocking shared flock on the private store root; A03 uses the same root's exclusive flock. A cooperating writer causes BUSY. Compare selected envelope and payload bytes and file identities again before a successful result; detect observed changes, root or directory replacement. This is not a kernel filesystem snapshot or proof against a malicious/uncooperative same-UID writer. **All legacy writers, cleanup and external modifications must be stopped**. Existing legacy writers do not honor the lock; stronger multiwriter migration requires a separate reviewed protocol and no direct bypass. Read errors/missing files, changed files, unsupported schema/budget, corruption and checkpoint mismatch fail closed with no checkpoint in result. Rejected diagnostics never echo payload, IDs, filesystem paths or private data.

## Orphan census

`audit_inventory(root)` is a separate operator-requested, bounded read-only census of the legacy `observations/` and `payloads/` namespaces. It enumerates both twice under the same shared lock, compares manifest digests, names and stat identities, checks canonical manifest references and generic envelope ID, and reports payload digests with no observation manifest reference, and referenced digests absent in that namespace. Counts unique payload files independently of observation count (dedup). It does not hash all payloads, validate all derivatives/fiducials, assess external references/replicas/retention, guarantee global availability or prove archive-wide integrity. Default/hard cap 512 visited entries total across the two passes (including bucket directories), 4 MiB total manifest bytes across passes; lower limits accepted. Unexpected files including temporary manifests, invalid manifests, missing directories, unstable inventory or exhausted budget yield INCOMPLETE with **no orphan candidates**. Larger archives need a separately designed indexed/streaming audit; do not silently return partial deletion lists.

An orphan is only a candidate recovery/inspection item; it can be an A03 partial write or still be referenced by external policy or derivatives. Never delete, overwrite, automatically repair or issue an erasure proof. The report explicitly sets deletion_allowed and archive_integrity_verified false. No cleanup or retention decisions move from A04 to A05.

## Example (trusted local offline owner only)

```python
from reality_ingress.integrity_inspection import verify_selected, audit_inventory

first = verify_selected(private_store_path, observation_id)
# Only if CHECKED, retain first.checkpoint.sha256 in an independent protected
# owner-controlled record, with its correct observation/store context.
later = verify_selected(private_store_path, observation_id,
                        expected_checkpoint_sha256=independently_retained_digest)
inventory = audit_inventory(private_store_path)
```

Do not expose this owner API as a consumer network endpoint. Checkpoint/report is separate from ObservationRef, not a mutation of its integrity flag. COG's existing whole-reference collision protection remains intact. Future approved sidecar/status transitions must preserve replay semantics and authorization. A04 policy/retention across restart, A05 stronger writer coordination and durable trusted checkpoint retention, A06 clock/replay, A07 hardware pilot remain open. No sensor I/O, permissions, History writer or physical certification.

## Test gates

Local synthetic tests exercise actual legacy store and generic records, exact checkpoint schema, old camera metadata vulnerability and new checkpoint comparison, raw versus semantic envelope identity, selected isolation, limits/private paths, cooperating lock, injected concurrent mutation, missing/corrupt payload and inventory dedup/orphans/partial census. Public CI also re-runs the actual pinned Core #17 characterization suite (Core-B/C/D independent pins) against additive RI checkout, preserving the original behavior. Parent workflows remain independent. No hardware, actual production vault, cryptographic signature, external archive, or durable transactional/power-loss certification. No automatic merge or deployment.

[Master #6](https://github.com/OpenRGD/rgd-reality-ingress/issues/6) · [RI-A04 #11](https://github.com/OpenRGD/rgd-reality-ingress/pull/11) · [Core #17](https://github.com/OpenRGD/openrgd/pull/17) · [RI-H10 return](https://github.com/OpenRGD/rgd-reality-ingress/pull/4#issuecomment-7172152368).
