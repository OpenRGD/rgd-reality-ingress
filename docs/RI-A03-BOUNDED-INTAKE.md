# RI-A03 — Bounded Intake v0.1 candidate

**26 November 2026. Linux local/offline only. Non-normative, non-actuating, no deployment.** Stacked on RI-A02B #9; historical contracts and files remain byte-identical.

## Scope and owners

The first implemented admission profile is `ri.imu-completed-spool.v0.1-candidate`. It accepts the existing source-owned finite IMU JSONL shape, not arbitrary sensor data, camera files, Voice metadata/PCM, CAL sidecars, lifecycle reports or COG's proposed normalized Console copy. The producer and source/robot/sensor/frame/session/boot labels are selected explicitly by the operator. Source labels are unverified claims; no label or completion report is a signature or an access grant.

Paky #8 and the reusable IMU-FOUNDATION-01D bridge define the compatible producer shapes. The latter carries assembly policy, receipt ages and host span as additional source metadata. This is profile support based on their reviewed shape, NOT a new public release, execution of private producer code, deployment or physical migration. Owner-side reruns remain required. Do not enable continuous export, create another serial reader or insert RI into the Console/Voice/Pulse live path.

## Two independent classes of limit

| Per-invocation resource limit | Maximum (can only lower) |
|---|---:|
| Input records, including duplicates | 60 |
| Raw JSONL row including LF | 4096 bytes |
| Total raw spool and separately canonical payload bytes | 256 KiB each |
| Planned payload + serialized envelope bytes (worst case) | 512 KiB |
| Source-order / wall-pair profile | Strictly increasing new sequence, nondecreasing receipt; span <=50ms |

These limits bound one operation, not the lifetime archive, filesystem block allocation or disk reservation. The original v0.4 CLI/ingest stays untouched. A03 reuses the optional native-u64 helper from A02B: sequence, original monotonic receipt, wall estimate, wall-pair span, nested publisher sequence/receipt and generalized receipt-age/span counters must be exact native integers in 0..2^64-1; source sequence and monotonic receipt are positive in this pilot. No coercion, truncation, JS number conversion or restamping. The 50ms semantic bracket constraint is independent of the type range and size limits. An integer value >2^53-1 is not rejected merely because a JavaScript Number cannot transport it safely. The profile is a proposal for these new interfaces only, not a schema restriction imposed on historical records.

## Explicit offline sequence

1. The existing acquisition owner finishes a finite opt-in export. Operator obtains the matching COMPLETED report and private finalized JSONL. No scan, watch, auto-import or auto-retry. Filename is derived from scope's session ID; report filename/count, optional written_bytes, enqueued count, error and authority flags checked. Final LF required, .part absent, exact row count. Report is a supplied claim, not cryptographic proof of completeness.
2. `preview_spool` reads one bounded snapshot using a private directory/file (same UID, 0700 directory, 0600 regular file, no symlink/hardlink, no FIFO); checks file identity/stat before/after read. Strict UTF-8 JSON, duplicate keys, nonfinite numbers, bounded nesting, exact allowed source/temporal/sample/wrapper shapes and scope, existing generic validator, native numeric helper and A02 content matcher. No store opened or written.
3. Collapse exact duplicate rows; reject conflicting content with the same sequence in this spool, distinct new observations out of order, receipt regression, or invalid last record before any write. Rebuild original v0.4 canonical payload/envelope for expected ID and size; internal unverified ref only for A02 validation, never issued as a recorded observation.
4. Explicit `apply_spool` on an existing private, canonical-path, **quiescent** EvidenceStore; supply prior preview raw SHA-256, re-read and validate same bytes. Preflight targeted existing payloads/envelopes, check exact bytes (not all-store verify), reject conflict/corruption or existing observation missing payload; existing identical orphan payload can be reused. Nonblocking advisory flock on store directory coordinates only A03 callers. Legacy writers do not honor it: operator must stop all other writers and prevent concurrent changes. Private same-UID trusted local files are a precondition, not a hostile-filesystem sandbox or stronger A05 race guarantee.
5. Call existing `generic.record_sample` for each distinct record. Same canonical payload, ID, serialized envelope as legacy import; no replacement of existing bytes. Per-record creation, not atomic multi-record transaction. No new store, manifest journal, re-key, source attestation or new reference issuance. Existing consumer ref API remains separate.

## Result and recovery

`PREVIEW` means valid input, no write. `REJECTED` means the attempt did not enter the write loop. `IMPORTED` reports confirmed record calls (new vs already present), not source verification or a complete archive integrity assessment. `PARTIAL_OR_UNCERTAIN` reports the confirmed prefix and failed input line; the last record may already exist or have only an orphan payload. An OS/process/power failure can also prevent the report from being returned. Never claim rollback of a batch. Inspect the store, quiesce other writers, retry explicitly using the identical spool hash. A repeated import is idempotent for exact content; uncertain commits can be recovered. No delete of spool, orphan, manifest or media; no automatic repair/GC. A04 owns retention/consent and cleanup policy, A05 owns stable scoped verification and storage integrity. A06 owns replay/time qualification. Same-key conflicts across other archives/spools are not globally checked by A03; A02 may compare an explicit candidate set later. No false freshness, History, Life or physical identity.

## Example (operator-approved sandbox, not an instruction to deploy)

```python
from reality_ingress.bounded_intake import SourceScope, preview_spool, apply_spool
from reality_ingress.evidence import EvidenceStore

# scope = SourceScope(producer, robot_id, sensor_id, source_id, frame_id, session_id, boot_id)
# completed = actual producer's COMPLETED report
preview = preview_spool(private_spool_directory, scope, completed)
if preview.status == "PREVIEW":
    # Only after explicit operator approval, with no other store writers:
    store = EvidenceStore(existing_private_absolute_store_directory)
    result = apply_spool(store, private_spool_directory, scope, completed,
                         expected_spool_sha256=preview.spool_sha256)
```

A03 is a local Python candidate API; no new CLI route or service. The caller must already have legitimate access to the inputs. The hash ties a preview to the bytes, not authorization. Actual ACL, consent and media access are not implemented. Do not invoke existing legacy verification on the live publisher.

## Verification and handoff

Local tests use synthetic samples matching the two reviewed producer profiles and actual frozen EvidenceStore/generic.record_sample/A02, check raw+canonical budgets, max u64, no-write validation, duplicate/collision, bad JSON, symlinks/FIFO/mode, corruption, lock contention and injected failure before/after manifest publication. CI also uses the real public Console #22 fixture and correlation helper with explicit synthetic source-profile metadata; this is not a private publisher execution. Existing A01, A02 and native profile regressions remain independent. Actual owner Paky/IMU rerun, resource benchmarks and operator pilot pending. The CAL exporter conformance in A02B remains pinned historical evidence; no new CAL scope or media transport.

Rollback: stop using this additive API, preserve files and use existing approved workflow. No merge/deployment or capture authorization follows from CI. See [master #6](https://github.com/OpenRGD/rgd-reality-ingress/issues/6), [RI-A02B #9](https://github.com/OpenRGD/rgd-reality-ingress/pull/9), [Paky #8](https://github.com/italiarobotica/paky-01/pull/8), [Console #22](https://github.com/OpenRGD/rgd-console/pull/22).
