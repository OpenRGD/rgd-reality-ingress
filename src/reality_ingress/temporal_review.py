"""RI-A06 — local, bounded temporal assessment of authorized-style stored evidence.

Historical presentation is not live delivery. No clock synchronization,
Chronograf qualification, acquisition, ACL, store IO, or History writes.
Trusted host owns the actual reader, clock context and presentation labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from threading import RLock
from time import monotonic_ns
from typing import Callable

from .bounded_intake import SourceScope, _validate_row, MAX_LINE_BYTES
from .evidence_access import AccessResult, _ref_profile
from .consumer_ref import unverified_ref_from_envelope
from .generic import canonical_json
from .interop_numeric import require_u64
from .session_binding import _decode, _token, SessionKey, MAX_REF_BYTES

PROFILE = "ri.temporal-assessment.v0.1-candidate"
MAX_RECORDS = 64
MAX_RECEIPT_AGE_NS = 60_000_000_000
PRESENTATIONS = frozenset({
    "ARCHIVE_READ", "IMPORT", "REIMPORT", "REPLAY", "SYNTHETIC", "UNKNOWN",
})


class TemporalError(ValueError):
    """Fixed diagnostic; never echo evidence, paths or labels."""


def _require(ok, code):
    if not ok:
        raise TemporalError(code)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _counter(value):
    try:
        return require_u64(value)
    except ValueError:
        raise TemporalError("OUTSIDE_NATIVE_U64_DOMAIN") from None


@dataclass(frozen=True)
class HostClock:
    """Host-declared clock context, not a verified device or time authority."""
    host_label: str
    clock_domain_id: str
    boot_id: str

    def __post_init__(self):
        _require(all(_token(v) for v in (self.host_label, self.clock_domain_id, self.boot_id))
                 and len(self.boot_id) <= 128, "INVALID_CLOCK_CONTEXT")

    def record(self):
        return {"host_label": self.host_label, "clock_domain_id": self.clock_domain_id,
                "boot_id": self.boot_id}


@dataclass(frozen=True)
class PublisherClockClaim:
    """Explicit trusted-host assertion of exact source/session clock scope.

    Equality of boot/domain labels alone is NOT proof of the same host.
    This object is an assertion from the host, not derived from the sample.
    """
    clock: HostClock
    source_id: str
    modality: str
    reference_frame_id: str
    session_id: str

    def __post_init__(self):
        _require(type(self.clock) is HostClock and
                 all(_token(v) for v in (self.source_id, self.modality,
                     self.reference_frame_id, self.session_id)), "INVALID_PUBLISHER_CLAIM")

    def matches(self, key: SessionKey):
        return (self.source_id, self.modality, self.reference_frame_id, self.session_id,
                self.clock.clock_domain_id, self.clock.boot_id) == (
                key.source_id, key.modality, key.reference_frame_id, key.session_id,
                key.clock_domain_id, key.boot_id)


@dataclass(frozen=True)
class HostOperationMark:
    """Optional separately supplied host-reported operation receipt.

    Not measured by this module. Never used to compute observation age.
    """
    operation: str
    clock: HostClock
    monotonic_ns: int

    def __post_init__(self):
        _require(type(self.operation) is str and self.operation in ("IMPORT", "VERIFY")
                 and type(self.clock) is HostClock, "INVALID_OPERATION_MARK")
        _counter(self.monotonic_ns)

    def record(self):
        return {"operation": self.operation, "clock": self.clock.record(),
                "monotonic_ns": self.monotonic_ns, "quality": "HOST_REPORTED"}


@dataclass(frozen=True)
class ReviewResult:
    status: str
    reason: str
    assessment_json: bytes | None = field(default=None, repr=False)


def _input(access):
    """Validate the already supplied A04 view; no new IO or authority.

    A local AccessResult object is not an authentication credential.
    """
    _require(type(access) is AccessResult, "INVALID_ACCESS_VIEW")
    _require(all(getattr(access, k) is False for k in
                 ("erasure_verified", "source_verified", "robot_binding_verified",
                  "history_committed", "actuation_enabled")), "UNSUPPORTED_AUTHORITY")
    _require((access.status, access.availability) in {
        ("REFERENCE_ONLY", "UNKNOWN"), ("PAYLOAD_RESOLVED", "AVAILABLE")},
        "ACCESS_VIEW_NOT_ELIGIBLE")
    ref = _decode(access.reference_json, MAX_REF_BYTES)
    immutable = _ref_profile(ref)
    key = None
    stamp = None
    if access.status == "REFERENCE_ONLY":
        _require(access.payload_bytes is None and ref["integrity_status"] == "not_verified"
                 and access.integrity_scope == "NOT_CHECKED", "INVALID_METADATA_VIEW")
    else:
        raw = access.payload_bytes
        _require(type(raw) is bytes and 0 < len(raw) <= MAX_LINE_BYTES
                 and ref["integrity_status"] == "verified_local_hash"
                 and access.integrity_scope == "SELECTED_LOCAL_SNAPSHOT",
                 "INVALID_PAYLOAD_VIEW")
        row = _decode(raw, MAX_LINE_BYTES)
        sample = row["payload"]["console_ingest_sample"]
        stamp = row["temporal_binding"]
        scope = SourceScope(row["producer_str"], sample["robot_id"], sample["sensor_id"],
            sample["source_id"], sample["sensor_frame_id"], sample["session_id"],
            stamp["clock_domain_ref"]["boot_id_str"])
        seq, mono, canonical, digest, obs, encoded = _validate_row(row, scope)
        # A03 reuses A02 and native-u64 profile. Reconstruct projection to
        # match the exact supplied reference; never reopen a store/envelope.
        env = _decode(encoded, 64 * 1024)
        _require(canonical == raw and _ref_profile(unverified_ref_from_envelope(env)) == immutable,
                 "SUPPLIED_CONTENT_MISMATCH")
        key = SessionKey(scope.source_id, "imu", scope.frame_id, scope.session_id, seq,
            stamp["clock_domain_ref"]["clock_domain_id_str"], scope.boot_id)
    return ref, _sha(immutable), key, stamp


class TemporalReview:
    """Owner-scoped, in-memory review ledger; no live promotion.

    Only a trusted local host may invoke this object on already authorized
    views. Restart does not restore replay knowledge or permissions.
    No eviction or silent reset. No global anti-replay guarantee.
    """

    def __init__(self, *, owner: object, clock: HostClock,
                 clock_ns: Callable[[], int] = monotonic_ns,
                 max_receipt_age_ns: int = 3_000_000_000,
                 max_records: int = MAX_RECORDS):
        _require(type(owner) is object and type(clock) is HostClock and callable(clock_ns),
                 "TRUSTED_HOST_REQUIRED")
        _require(type(max_records) is int and 0 < max_records <= MAX_RECORDS
                 and type(max_receipt_age_ns) is int
                 and 0 < max_receipt_age_ns <= MAX_RECEIPT_AGE_NS, "INVALID_REVIEW_LIMIT")
        self._owner, self._context, self._clock = owner, clock, clock_ns
        self._age_limit, self._max_records = max_receipt_age_ns, max_records
        self._lock = RLock()
        self._closed = False
        self._last = -1
        self._seen: dict[str, str] = {}
        self._keys: dict[SessionKey, tuple[str, int, bool]] = {}

    def _now(self):
        _require(not self._closed, "REVIEW_CLOSED")
        try:
            now = _counter(self._clock())
            _require(now >= self._last, "ASSESSMENT_CLOCK_REGRESSION")
        except Exception:
            self._closed = True
            self._seen.clear()
            self._keys.clear()
            raise TemporalError("ASSESSMENT_CLOCK_INVALID_OR_REGRESSED") from None
        self._last = now
        return now

    def close(self, owner):
        with self._lock:
            _require(owner is self._owner, "OWNER_REQUIRED")
            self._closed = True
            self._seen.clear()
            self._keys.clear()

    def stats(self, owner):
        with self._lock:
            _require(owner is self._owner, "OWNER_REQUIRED")
            return {"closed": self._closed, "records": len(self._seen),
                    "bound_keys": len(self._keys), "durable_replay_protection": False}

    @staticmethod
    def _stream(key):
        return (key.source_id, key.modality, key.reference_frame_id,
                key.session_id, key.clock_domain_id, key.boot_id)

    def _sequence(self, key, obs, mono, aligned):
        if key is None:
            return "NOT_RESOLVED"
        previous = self._keys.get(key)
        _require(previous is None or previous[:2] == (obs, mono), "SESSION_SEQUENCE_COLLISION")
        peers = [(k.sequence, received, peer_aligned)
                 for k, (_, received, peer_aligned) in self._keys.items()
                 if self._stream(k) == self._stream(key) and k != key]
        # Sequence ordering refers only to the declared source/session scope.
        # Compare receipt values only when BOTH records independently received
        # the same local host/boot/domain assertion. Labels alone are not clocks.
        for sequence, received, peer_aligned in peers:
            if aligned and peer_aligned:
                _require(not (key.sequence > sequence and mono < received)
                         and not (key.sequence < sequence and mono > received),
                         "SOURCE_RECEIPT_ORDER_CONFLICT")
        if not peers:
            return "FIRST_IN_SCOPE"
        return "OUT_OF_ORDER" if key.sequence < max(s for s, _, _ in peers) else "IN_ORDER"

    def _mark(self, mark, operation, now):
        if mark is None:
            return None
        _require(type(mark) is HostOperationMark and mark.operation == operation,
                 "OPERATION_ROLE_MISMATCH")
        if mark.clock == self._context:
            _require(mark.monotonic_ns <= now, "FUTURE_OPERATION_MARK")
        return mark.record()

    def assess(self, owner, access: AccessResult, *,
               presentation: str = "ARCHIVE_READ",
               publisher_clock: PublisherClockClaim | None = None,
               import_mark: HostOperationMark | None = None,
               verification_mark: HostOperationMark | None = None) -> ReviewResult:
        """Return a separate temporal sidecar, never modify or reissue a ref.

        Stored views are always non-live, including if original receipt is recent.
        Duplicate reports are inert; no newly refreshed timestamp or sidecar.
        """
        with self._lock:
            if owner is not self._owner:
                return ReviewResult("BLOCKED", "OWNER_REQUIRED")
            try:
                _require(type(presentation) is str and presentation in PRESENTATIONS,
                         "INVALID_PRESENTATION")
                _require(publisher_clock is None or type(publisher_clock) is PublisherClockClaim,
                         "INVALID_PUBLISHER_CLAIM")
                now = self._now()
                ref, fingerprint, key, stamp = _input(access)
                obs = ref["observation_id"]
                original = ref["time"]
                mono = original["received_monotonic_ns"]
                known = self._seen.get(obs)
                _require(known is None or known == fingerprint, "OBSERVATION_ID_COLLISION")
                aligned = (key is not None and publisher_clock is not None
                           and publisher_clock.matches(key)
                           and publisher_clock.clock == self._context)
                order = self._sequence(key, obs, mono, aligned)
                if aligned:
                    _require(mono <= now, "FUTURE_ORIGINAL_RECEIPT")
                # Validate operation roles even for repeat presentations.
                imported = self._mark(import_mark, "IMPORT", now)
                verified = self._mark(verification_mark, "VERIFY", now)
                if known is not None:
                    # A metadata-first view may gain a checked key internally,
                    # but does not publish a new report or refresh the prior view.
                    if key is not None and key not in self._keys:
                        self._keys[key] = (obs, mono, False)
                    return ReviewResult("DUPLICATE", "INERT_REPRESENTATION")
                _require(len(self._seen) < self._max_records, "REVIEW_BACKPRESSURE")
                age = now - mono if aligned else None
                age_state = ("UNKNOWN" if age is None else
                             "STALE_RECEIPT" if age >= self._age_limit else "RECENT_RECEIPT")
                record = {
                    "schema_version": PROFILE,
                    "observation_id": obs,
                    # Only comparison identity excludes mutable integrity flag;
                    # never use as source identity or a new ObservationRef.
                    "reference_content_sha256": fingerprint,
                    "payload_sha256_hex": ref["payload_sha256_hex"],
                    "presentation": presentation,
                    "sequence_relation": order,
                    "source_session_id": key.session_id if key is not None else None,
                    "original_receipt": {
                        "clock_domain_id": original["clock_domain_id"],
                        "boot_id": original["boot_id"],
                        "received_monotonic_ns": mono,
                        "received_unix_estimate_ns": stamp["received_unix_estimate_ns"] if stamp else None,
                        "host_wall_pair_span_ns": stamp["host_wall_pair_span_ns"] if stamp else None,
                        "receive_timestamp_method": stamp["receive_timestamp_method"] if stamp else None,
                    },
                    "publisher_host_label": (publisher_clock.clock.host_label
                        if key is not None and publisher_clock is not None
                        and publisher_clock.matches(key) else None),
                    "receipt_clock_relation": "HOST_SAME_BOOT_ASSERTED" if aligned else "NOT_ESTABLISHED",
                    "receipt_age_ns": age,
                    "receipt_age_state": age_state,
                    "receipt_age_limit_ns": self._age_limit,
                    "assessment_clock": self._context.record(),
                    "assessment_monotonic_ns": now,
                    "import_mark": imported,
                    "verification_mark": verified,
                    "source_measurement_time": None,
                    "source_time_status": "UNKNOWN",
                    "source_measurement_freshness": "UNKNOWN",
                    "source_time_uncertainty_ns": None,
                    "chronograf_anchor_ref": None,
                    "chronograf_status": "UNRESOLVED",
                    "live_delivery": False,
                    "source_verified": False,
                    "robot_binding_verified": False,
                    "history_committed": False,
                    "actuation_enabled": False,
                    "decision_eligible": False,
                }
                encoded = canonical_json(record)
                self._seen[obs] = fingerprint
                if key is not None:
                    self._keys[key] = (obs, mono, aligned)
                return ReviewResult("ASSESSED", "STORED_EVIDENCE_ONLY", encoded)
            except TemporalError as exc:
                return ReviewResult("REJECTED", str(exc))
            except (ValueError, KeyError, TypeError, RuntimeError, OverflowError, RecursionError):
                return ReviewResult("REJECTED", "INVALID_OR_INCONSISTENT_VIEW")
