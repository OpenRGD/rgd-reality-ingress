"""RI-A04 local candidate: scoped evidence reads and availability.

A trusted host controls this in-process object. Not an authentication service,
sandbox, legal-consent verifier, durable vault, transport or deletion engine.
No legacy API changes. A05 must review stable storage verification.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock
from time import monotonic_ns
from typing import Callable

from .bounded_intake import (
    IntakeError, SourceScope, _owner_dir, _read_private_file, _validate_row,
    MAX_LINE_BYTES,
)
from .consumer_ref import unverified_ref_from_envelope
from .evidence import IntegrityError
from .generic import MEDIA_TYPE, SCHEMA_REF as GENERIC_SCHEMA, canonical_json, verify_generic_envelope
from .interop_numeric import check_ref_integer_domain, NumericDomainError
from .session_binding import (
    BindingError, CAMERA_SCHEMA, MAX_REF_BYTES, SuppliedEvidence, resolve_session, _decode,
)

PROFILE = "ri.evidence-access.local.v0.1-candidate"
MAX_ENVELOPE_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = MAX_LINE_BYTES
MAX_POLICY_RECORDS = 64
MAX_CHANNELS = 64
MAX_READS = 60
MAX_RELEASE_BYTES = 256 * 1024
MAX_LEASE_SECONDS = 3600
MAX_LOCAL_RETENTION_SECONDS = 86400
PURPOSES = frozenset({"operator_review", "diagnostics", "calibration", "cognition", "perception"})
WITHHOLD_STATES = frozenset({"RESTRICTED", "REDACTED", "ERASURE_REPORTED"})
_ID = re.compile(r"obs_[0-9a-f]{32}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class AccessError(ValueError):
    """Fixed policy error code; never includes evidence, identity or path."""


def _require(condition, code):
    if not condition:
        raise AccessError(code)


def _bounded(value, ceiling):
    return type(value) is int and 0 < value <= ceiling


@dataclass(frozen=True)
class AccessResult:
    status: str
    availability: str
    reason: str
    # Avoid accidentally printing payload/metadata in repr/logs.
    reference_json: bytes | None = field(default=None, repr=False)
    payload_bytes: bytes | None = field(default=None, repr=False)
    integrity_scope: str = "NOT_CHECKED"
    erasure_verified: bool = False
    source_verified: bool = False
    robot_binding_verified: bool = False
    history_committed: bool = False
    actuation_enabled: bool = False


@dataclass(frozen=True)
class _Policy:
    expected: bytes = field(repr=False)
    purposes: frozenset[str]
    retention_deadline_ns: int
    metadata_consent: bool
    payload_consent: bool
    metadata_state: str = "ELIGIBLE"
    payload_state: str = "ELIGIBLE"


@dataclass(frozen=True)
class _Lease:
    observation_id: str
    purpose: str
    payload_allowed: bool
    deadline_ns: int
    max_payload_bytes: int
    reads_left: int
    bytes_left: int
    revoked: bool = False


def _denied(reason="ACCESS_NOT_GRANTED", availability="NOT_AUTHORIZED"):
    return AccessResult("BLOCKED", availability, reason)


def _unavailable(reason, availability="UNAVAILABLE"):
    return AccessResult("UNAVAILABLE", availability, reason)


def _ref_profile(ref):
    """Validate supported local projection domain, not arbitrary new schemas."""
    _require(type(ref) is dict and set(ref) == {
        "schema_version", "observation_id", "source_id", "modality", "reference_frame_id",
        "sample_sequence", "payload_sha256_hex", "payload_media_type", "payload_size_bytes",
        "origin_status", "integrity_status", "source_verified", "robot_binding_verified",
        "history_committed", "actuation_enabled", "time",
    } and ref.get("schema_version") ==
             "ri.consumer-observation-ref.v0.1-candidate", "INVALID_REFERENCE")
    _require(type(ref.get("observation_id")) is str and _ID.fullmatch(ref["observation_id"])
             and type(ref.get("payload_sha256_hex")) is str and
             _SHA.fullmatch(ref["payload_sha256_hex"]), "INVALID_REFERENCE")
    _require((ref.get("modality"), ref.get("payload_media_type")) in
             {("imu", MEDIA_TYPE), ("rgb", "image/jpeg")}, "UNSUPPORTED_EVIDENCE_PROFILE")
    _require(ref.get("origin_status") == "unknown" and
             ref.get("integrity_status") in ("not_verified", "verified_local_hash")
             and all(ref.get(k) is False for k in ("source_verified", "robot_binding_verified",
                                                  "history_committed", "actuation_enabled")),
             "UNSUPPORTED_REFERENCE_AUTHORITY")
    check_ref_integer_domain(ref)
    time = ref["time"]
    _require(type(time) is dict and set(time) == {
        "clock_domain_id", "boot_id", "received_monotonic_ns", "source_time_status",
        "source_measurement_time", "chronograf_anchor_ref",
    } and time.get("source_time_status") == "unknown" and
             "source_measurement_time" in time and time["source_measurement_time"] is None and
             "chronograf_anchor_ref" in time and time["chronograf_anchor_ref"] is None,
             "UNSUPPORTED_TIME_AUTHORITY")
    boot = time.get("boot_id")
    _require(boot is None or (type(boot) is str and 0 < len(boot) <= 128), "INVALID_BOOT_LABEL")
    for value, maximum in ((ref.get("source_id"), 256),
                           (ref.get("reference_frame_id"), 256),
                           (time.get("clock_domain_id"), 256)):
        _require(type(value) is str and 0 < len(value) <= maximum, "INVALID_REFERENCE_LABEL")
    # Normalize only the local-verification flag for comparison. Never modify
    # supplied objects, derive a new observation ID or return an owner assertion
    # of previously verified bytes without checking them.
    expected = dict(ref, integrity_status="not_verified")
    data = canonical_json(expected)
    _require(len(data) <= MAX_REF_BYTES, "REFERENCE_BYTE_LIMIT")
    return data


class LocalEvidenceReader:
    """Read-only local broker with opaque channels and fail-closed policy.

    Owner channel and reader channels are process-local objects; host owns
    authentication and all callers share the trusted Python process. No
    security isolation from malicious Python code or legacy direct readers.
    """

    def __init__(self, root: Path, *, owner: object, clock_ns: Callable[[], int] = monotonic_ns):
        _require(type(owner) is object and callable(clock_ns), "TRUSTED_HOST_REQUIRED")
        # No EvidenceStore constructor: no directory creation by a reader.
        self._root = Path(root)
        fd = _owner_dir(self._root)
        try:
            info = os.fstat(fd)
            self._root_identity = (info.st_dev, info.st_ino)
        finally:
            os.close(fd)
        self._owner, self._clock = owner, clock_ns
        self._lock = RLock()
        self._closed = False
        self._last = -1
        self._policies: dict[str, _Policy] = {}
        self._leases: dict[object, _Lease] = {}
        self._counts = {"metadata_releases": 0, "payload_releases": 0,
                        "payload_bytes_released": 0, "blocked": 0, "unavailable": 0}

    def _now(self):
        if self._closed:
            raise AccessError("READER_CLOSED")
        try:
            now = self._clock()
            _require(type(now) is int and 0 <= now and now >= self._last,
                     "LOCAL_CLOCK_INVALID_OR_REGRESSED")
        except Exception:
            self._closed = True
            self._leases.clear()
            self._policies.clear()
            raise AccessError("LOCAL_CLOCK_INVALID_OR_REGRESSED") from None
        self._last = now
        return now

    def _admin(self, owner):
        _require(owner is self._owner, "OWNER_REQUIRED")
        return self._now()

    def register_evidence(self, owner, reference_json: bytes, *,
                          purposes: frozenset[str], retention_seconds: int,
                          metadata_consent: bool = False, payload_consent: bool = False):
        """One explicit host decision for exact ref labels and content digest.

        Consent booleans represent external owner decisions, not verified
        subject consent. Retention is a local access deadline, not deletion.
        No reopening/extension of an existing policy in this reader instance.
        """
        with self._lock:
            now = self._admin(owner)
            _require(type(purposes) is frozenset and bool(purposes) and
                     purposes <= PURPOSES and _bounded(retention_seconds, MAX_LOCAL_RETENTION_SECONDS),
                     "INVALID_POLICY_SCOPE")
            _require(type(metadata_consent) is bool and type(payload_consent) is bool
                     and (not payload_consent or metadata_consent), "INVALID_CONSENT_SCOPE")
            try:
                ref = _decode(reference_json, MAX_REF_BYTES)
                expected = _ref_profile(ref)
            except (AccessError, BindingError, NumericDomainError, TypeError, KeyError, ValueError):
                raise AccessError("INVALID_REFERENCE_PROFILE") from None
            obs = ref["observation_id"]
            _require(obs not in self._policies and len(self._policies) < MAX_POLICY_RECORDS,
                     "POLICY_EXISTS_OR_LIMIT")
            # First wave: only bounded original IMU payloads. Camera metadata
            # can be scoped separately; image/audio transfer remains blocked.
            _require(not payload_consent or ref["modality"] == "imu",
                     "MEDIA_PAYLOAD_REVIEW_REQUIRED")
            self._policies[obs] = _Policy(expected, purposes,
                now + retention_seconds * 1_000_000_000, metadata_consent, payload_consent)

    def grant(self, owner, observation_id: str, *, purpose: str, ttl_seconds: int,
              payload: bool = False, max_reads: int = 1,
              max_payload_bytes: int = MAX_PAYLOAD_BYTES,
              max_total_payload_bytes: int = MAX_RELEASE_BYTES) -> object:
        """Mint a local reader channel, not a reference-as-token or remote grant."""
        with self._lock:
            now = self._admin(owner)
            _require(type(observation_id) is str and type(purpose) is str and
                     type(payload) is bool and _bounded(ttl_seconds, MAX_LEASE_SECONDS) and
                     _bounded(max_reads, MAX_READS) and _bounded(max_payload_bytes, MAX_PAYLOAD_BYTES)
                     and _bounded(max_total_payload_bytes, MAX_RELEASE_BYTES),
                     "INVALID_LEASE")
            p = self._policies.get(observation_id)
            _require(p is not None and p.metadata_consent and p.metadata_state == "ELIGIBLE"
                     and purpose in p.purposes and now < p.retention_deadline_ns
                     and (not payload or (p.payload_consent and p.payload_state == "ELIGIBLE")),
                     "POLICY_DENIED")
            _require(len(self._leases) < MAX_CHANNELS, "CHANNEL_LIMIT")
            channel = object()
            self._leases[channel] = _Lease(observation_id, purpose, payload,
                min(now + ttl_seconds * 1_000_000_000, p.retention_deadline_ns),
                max_payload_bytes, max_reads, max_total_payload_bytes)
            return channel

    def revoke(self, owner, channel):
        with self._lock:
            self._admin(owner)
            _require(type(channel) is object and channel in self._leases, "UNKNOWN_CHANNEL")
            self._leases[channel] = replace(self._leases[channel], revoked=True)

    def withhold(self, owner, observation_id: str, *, scope: str, state: str):
        """One-way local withholding, never a redaction or erasure operation."""
        with self._lock:
            self._admin(owner)
            _require(type(observation_id) is str and observation_id in self._policies and
                     scope in ("metadata", "payload") and type(state) is str and
                     state in WITHHOLD_STATES, "INVALID_WITHHOLD")
            p = self._policies[observation_id]
            if scope == "metadata":
                _require(p.metadata_state == "ELIGIBLE", "ALREADY_WITHHELD")
                self._policies[observation_id] = replace(p, metadata_state=state)
            else:
                _require(p.payload_state == "ELIGIBLE", "ALREADY_WITHHELD")
                self._policies[observation_id] = replace(p, payload_state=state)

    def stats(self, owner):
        with self._lock:
            _require(owner is self._owner, "OWNER_REQUIRED")
            return dict(self._counts, closed=self._closed,
                        policy_records=len(self._policies), channels=len(self._leases))

    def close(self, owner):
        with self._lock:
            _require(owner is self._owner, "OWNER_REQUIRED")
            self._closed = True
            self._policies.clear()
            self._leases.clear()

    def _count(self, result):
        if result.status == "BLOCKED":
            self._counts["blocked"] += 1
        elif result.status == "UNAVAILABLE":
            self._counts["unavailable"] += 1
        elif result.status == "REFERENCE_ONLY":
            self._counts["metadata_releases"] += 1
        elif result.status == "PAYLOAD_RESOLVED":
            self._counts["payload_releases"] += 1
            self._counts["payload_bytes_released"] += len(result.payload_bytes)
        return result

    def _gate(self, channel, observation_id, purpose, include_payload, now):
        # Unknown channel, wrong ID/purpose or unapproved scope all return the
        # same response without touching disk, including if the ID is absent.
        if (type(channel) is not object or type(observation_id) is not str or
                type(purpose) is not str or type(include_payload) is not bool):
            return _denied()
        lease = self._leases.get(channel)
        if (lease is None or lease.revoked or lease.observation_id != observation_id
                or lease.purpose != purpose or (include_payload and not lease.payload_allowed)):
            return _denied()
        p = self._policies[observation_id]
        if not p.metadata_consent:
            return _denied()
        if now >= p.retention_deadline_ns:
            return _denied("RETENTION_EXPIRED", "EXPIRED")
        if now >= lease.deadline_ns:
            return _denied("LEASE_EXPIRED")
        state = p.metadata_state
        if state != "ELIGIBLE":
            return _denied("METADATA_WITHHELD", state)
        if include_payload:
            if not p.payload_consent:
                return _denied()
            if p.payload_state != "ELIGIBLE":
                return _denied("PAYLOAD_WITHHELD", p.payload_state)
        if lease.reads_left <= 0:
            return _denied("READ_BUDGET_EXHAUSTED")
        return None

    def _root_check(self):
        fd = _owner_dir(self._root)
        try:
            info = os.fstat(fd)
            _require((info.st_dev, info.st_ino) == self._root_identity, "STORE_ROOT_CHANGED")
        finally:
            os.close(fd)

    def _read_at(self, directory, filename, limit):
        # Names are constructed from strict ID/digest, never supplied paths.
        self._root_check()
        try:
            fd = _owner_dir(directory)
        except FileNotFoundError:
            return None
        try:
            return _read_private_file(fd, filename, limit, missing_ok=True)
        finally:
            os.close(fd)

    def _resolve(self, p, lease, include_payload):
        env_raw = self._read_at(self._root / "observations",
                                lease.observation_id + ".json", MAX_ENVELOPE_BYTES)
        if env_raw is None:
            return _unavailable("OBSERVATION_NOT_FOUND", "MISSING")
        env = _decode(env_raw, MAX_ENVELOPE_BYTES)
        ref = unverified_ref_from_envelope(env)
        _require(ref["observation_id"] == lease.observation_id and
                 _ref_profile(ref) == p.expected, "REFERENCE_SCOPE_OR_CONTENT_MISMATCH")
        digest = ref["payload_sha256_hex"]
        _require(env["evidence"]["payload_ref_str"] ==
                 f"payloads/{digest[:2]}/{digest}.bin", "NONCANONICAL_PAYLOAD_REF")
        if env["schema_ref_str"] == GENERIC_SCHEMA:
            verify_generic_envelope(env)
        elif env["schema_ref_str"] != CAMERA_SCHEMA or ref["modality"] != "rgb":
            raise AccessError("UNSUPPORTED_ENVELOPE_PROFILE")
        # No payload open, size probe, availability check or inherited
        # verified_local_hash flag for metadata-only access.
        if not include_payload:
            return AccessResult("REFERENCE_ONLY", "UNKNOWN", "METADATA_SCOPE_ONLY",
                                reference_json=canonical_json(ref))
        _require(env["schema_ref_str"] == GENERIC_SCHEMA and ref["modality"] == "imu",
                 "MEDIA_PAYLOAD_REVIEW_REQUIRED")
        size = ref["payload_size_bytes"]
        if not 0 < size <= min(lease.max_payload_bytes, lease.bytes_left, MAX_PAYLOAD_BYTES):
            return _denied("PAYLOAD_BYTE_BUDGET")
        raw = self._read_at(self._root / "payloads" / digest[:2], digest + ".bin", size)
        if raw is None:
            return _unavailable("PAYLOAD_NOT_FOUND", "MISSING")
        _require(len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
                 "PAYLOAD_HASH_OR_SIZE_MISMATCH")
        # Reuse A03's source-profile validation and A02's existing content
        # correlation; no second producer/format or new authority. Scope labels
        # here describe stored content, not independently authenticated identity.
        row = _decode(raw, MAX_PAYLOAD_BYTES)
        sample = row["payload"]["console_ingest_sample"]
        scope = SourceScope(row["producer_str"], sample["robot_id"], sample["sensor_id"],
            sample["source_id"], sample["sensor_frame_id"], sample["session_id"],
            row["temporal_binding"]["clock_domain_ref"]["boot_id_str"])
        _validate_row(row, scope)
        resolved = resolve_session(SuppliedEvidence(canonical_json(ref), env_raw, raw))
        _require(resolved.status == "CONTENT_MATCHED", "GENERIC_CONTENT_MISMATCH")
        # Compare selected envelope again, not a global store scan. A05 owns
        # stronger snapshot/transaction semantics. Trusted quiescent store
        # remains a precondition, not a hostile-filesystem guarantee.
        after = self._read_at(self._root / "observations",
                              lease.observation_id + ".json", MAX_ENVELOPE_BYTES)
        _require(after == env_raw, "ENVELOPE_CHANGED_DURING_READ")
        checked = dict(ref, integrity_status="verified_local_hash")
        return AccessResult("PAYLOAD_RESOLVED", "AVAILABLE", "SELECTED_CONTENT_CHECKED",
                            reference_json=canonical_json(checked), payload_bytes=raw,
                            integrity_scope="SELECTED_LOCAL_SNAPSHOT")

    def read(self, channel, observation_id: str, *, purpose: str,
             include_payload: bool = False) -> AccessResult:
        """Explicit purpose and scope; never use observation ID as access token.

        Checks are serialized with local policy mutation. Revocation affects
        subsequent calls, not data already returned or a call linearized before
        revocation. TTL is rechecked immediately before returning bytes.
        """
        with self._lock:
            try:
                now = self._now()
            except AccessError:
                return self._count(_denied("READER_UNAVAILABLE", "UNKNOWN"))
            blocked = self._gate(channel, observation_id, purpose, include_payload, now)
            if blocked is not None:
                return self._count(blocked)
            lease = self._leases[channel]
            p = self._policies[observation_id]
            # Authorized attempts consume read budget even when evidence is
            # absent/corrupt. No unlimited retry loop; charge bytes only on release.
            try:
                result = self._resolve(p, lease, include_payload)
            except (AccessError, IntegrityError, BindingError, NumericDomainError,
                    IntakeError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
                result = _unavailable("CONTENT_OR_PROFILE_REJECTED", "CORRUPT_OR_UNSUPPORTED")
            except (OSError, RuntimeError):
                result = _unavailable("LOCAL_READ_UNAVAILABLE")
            try:
                now = self._now()
            except AccessError:
                return self._count(_denied("READER_UNAVAILABLE", "UNKNOWN"))
            late = self._gate(channel, observation_id, purpose, include_payload, now)
            if late is not None:
                result = late
            charged = len(result.payload_bytes) if result.payload_bytes is not None else 0
            self._leases[channel] = replace(lease, reads_left=lease.reads_left - 1,
                                            bytes_left=lease.bytes_left - charged)
            return self._count(result)
