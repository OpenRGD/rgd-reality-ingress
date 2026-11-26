# RI-A02B — CAL-021-C compatibility closure before bounded intake

**26 November 2026 · candidate · offline · no new authority.**

This is a small additive reconciliation before RI-A03, stacked on RI-A02 #8 at `161318d2897d07d5628ef502cafba1c7c489fff0`. It is not a new owner-side protocol, normative contract, evidence ingestion or resolver rollout.

## Review and exact evidence

[CAL #9](https://github.com/OpenRGD/rgd-calibration/pull/9), head `646dbc05bcefd15942b25bb55b3c99096f0cccc9`, open for review; [handoff](https://github.com/OpenRGD/rgd-calibration/blob/646dbc05bcefd15942b25bb55b3c99096f0cccc9/docs/handoffs/CAL-021-C-TO-REALITY-INGRESS.md), [CI](https://github.com/OpenRGD/rgd-calibration/actions/runs/45806326568). All eight owner push/PR workflow results were checked at this head. The decoded exchange job reports five accepted inputs (three actual RI projections), twenty Rust sidecars and fourteen rejected inputs. Camera verified/unverified and generic unverified references are distinct: the generic projection is not a verified persisted sample. The actual store rejects corrupt camera payload. CAL does NOT execute RI-A02 resolve_session. No sensor trial, authorization, source binding or depth certification follows.

The new [CAL-scoped registry snapshot](compatibility/registry.snapshot-2026-11-26-cal-021-c.json) appends CAL-021-C to the original A01 manifest format, preserving every previous integration and the old snapshot. Seven of ten original targets remain returned in this snapshot; CAL adds an evidence record, not a new target. This is deliberately a CAL-only update; other new returns (including COG-RI-02 and IMU foundation) need their own audited registry revisions. The original registry validator can validate this additional snapshot using the existing schema; the new tests compare it to the frozen historical snapshot. No schema repin, no edit to the first snapshot or parent branches.

## Proposed native integer domain (owner review required)

Frozen RI ref v0.1 declares nonnegative JSON Schema integers without maximum. CAL uses Rust u64 for sample_sequence, payload_size_bytes and time.received_monotonic_ns; unlike JSON Schema's mathematical integer definition, Rust as_u64 rejects decimal/exponent representations parsed as floats.

For **new** native Python/Rust intake/export compatibility, propose `ri.native-u64.v0.1-candidate`: exact integer values in [0, 18446744073709551615], no bools, floats, numeric strings, clipping, wrapping, rounding or silent rescaling. A value outside that domain is rejected by the new optional profile, not retroactively declared invalid by the old schema. The additive helper `reality_ingress.interop_numeric` checks the three reference counters only and can be reused for future integer admission fields; callers still validate the real schema, typed payload and all authority rules. It is not wired into any existing producer, reader or A02 API.

A03 should apply exact-integer bounds to new generic sequence/receipt counters, wall estimate and clock-pair span only after declaring the relevant intake profile; byte/record/queue budgets are separate and much smaller than the numeric type limit. No new record or quota is implemented here. Do not cap existing monotonic or wall timestamps at 2^53-1: nanosecond clocks can exceed the JS safe range. The native profile supports lossless u64. For any future JSON/JS consumer that parses numbers to binary64, only 0..9007199254740991 is reliably safe; values beyond that require a reviewed lossless codec (e.g. explicit decimal strings in a versioned transport/profile) or rejection of that transport, not a silent change to existing v0.1 number fields. No negotiation or new wire representation is implemented.

Unicode schema string lengths count Unicode code points, not UTF-8 bytes; separate actual input byte limits are still needed. CAL now matches this interpretation for its reference input. RI-A02 session key tokens intentionally have a narrower ASCII-oriented candidate profile. A schema-valid CAL metadata reference is not necessarily resolvable by A02; this remains an explicit owner review gap, not a reason to normalize labels or alter historic IDs.

## Separate responsibilities

- RI owns original observation bytes, provenance and references. A02 compares only already supplied immutable bytes; no store lookup, proof of access/availability, host/device identity or verified session authority. Do not duplicate this in CAL.
- A03 validates and bounds future explicitly supplied intake; CAL sidecars are not sensor samples or an instruction to acquire a frame.
- A04 owns authorized scoped metadata/media resolution, consent, availability, retention and denial. A valid reference is not a capability token. CAL receives only allowed data.
- A05 owns stable verification; payload hash is not complete legacy camera metadata integrity. Source index match is not identity or metrological proof.
- CAL owns associations, revisions, sealed profiles and validation; validate the nested reference against exact RI schema AND the sidecar against exact CAL schema. The CAL wrapper schema alone does not validate the nested reference. Preserve observation ID, hash, source time and authority flags. Perception metric depth stays blocked; no new camera opener or robot control.
- Chronograf/History/identity/effect permissions remain independent.

## Acceptance

The optional native counter helper rejects unsupported representations without changing references. The new snapshot must preserve every prior record and validate against the original manifest schema. Cross-language tests check exact pinned CAL Rust fixture exporter against synthetic RI producer references, separately validate RI and CAL output schemas, and characterize schema-valid but unsupported u64 overflow/integral-float values. A matching numeric test proves representation compatibility only. No automatic promotion, hardware deployment, Registry installation or merge. Send result back to CAL #9 for joint review; continue A03 with these constraints, not with an assumed new approved standard.
