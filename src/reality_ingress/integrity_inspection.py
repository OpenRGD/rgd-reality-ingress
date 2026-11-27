"""RI-A05 — bounded, offline, owner-side integrity inspection.

Not a consumer reader, grant, source attestation, vault, repair or GC tool.
Private quiescent local store required; A03 writers cooperate via flock.
The original observation identifiers and stored bytes are never changed.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat

from .bounded_intake import IntakeError, _owner_dir, _read_private_file, _fingerprint
from .consumer_ref import unverified_ref_from_envelope
from .generic import (
    SCHEMA_REF as GENERIC_SCHEMA, MAX_SAMPLE_BYTES, canonical_json,
    envelope_from_sample, validate_sample,
)
from .session_binding import BindingError, CAMERA_SCHEMA, _decode

PROFILE = "ri.integrity-checkpoint.v0.1-candidate"
MAX_ENVELOPE_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
MAX_INVENTORY_ENTRIES = 512
MAX_INVENTORY_BYTES = 4 * 1024 * 1024
_ID = re.compile(r"obs_[0-9a-f]{32}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_BUCKET = re.compile(r"[0-9a-f]{2}\Z")


class InspectionError(ValueError):
    """Fixed diagnostic codes, no private path, payload or input text."""


def _require(ok, code):
    if not ok:
        raise InspectionError(code)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _limit(value, maximum):
    return type(value) is int and 0 < value <= maximum


@dataclass(frozen=True)
class IntegrityCheckpoint:
    """Current exact bytes, not proof of original capture or timestamp.

    Persist the checkpoint digest independently under owner control. A digest
    stored alongside mutable evidence is not an independent trust anchor.
    """
    observation_id: str
    envelope_schema: str
    envelope_sha256: str
    envelope_size_bytes: int
    payload_sha256: str
    payload_size_bytes: int

    def canonical_bytes(self):
        return canonical_json({
            "schema_version": PROFILE,
            "observation_id": self.observation_id,
            "envelope_schema": self.envelope_schema,
            "envelope_sha256": self.envelope_sha256,
            "envelope_size_bytes": self.envelope_size_bytes,
            "payload_sha256": self.payload_sha256,
            "payload_size_bytes": self.payload_size_bytes,
        })

    @property
    def sha256(self):
        return _sha(self.canonical_bytes())


@dataclass(frozen=True)
class IntegrityReport:
    status: str
    reason: str
    envelope_integrity: str = "NOT_CHECKED"
    payload_integrity: str = "NOT_CHECKED"
    checkpoint_status: str = "NOT_CHECKED"
    checkpoint: IntegrityCheckpoint | None = field(default=None, repr=False)
    source_verified: bool = False
    robot_binding_verified: bool = False
    history_committed: bool = False
    actuation_enabled: bool = False
    historical_capture_verified: bool = False
    access_verified: bool = False


@dataclass(frozen=True)
class InventoryReport:
    status: str
    reason: str
    examined_entries: int = 0
    observation_manifests: int = 0
    payload_files: int = 0
    candidate_orphan_count: int = 0
    missing_payload_count: int = 0
    # Owner-only diagnostics; avoid IDs/digests in logs/repr.
    candidate_orphan_digests: tuple[str, ...] = field(default=(), repr=False)
    missing_payload_digests: tuple[str, ...] = field(default=(), repr=False)
    deletion_allowed: bool = False
    archive_integrity_verified: bool = False


def _dir_identity(fd):
    st = os.fstat(fd)
    return (st.st_dev, st.st_ino)


def _open_child(parent, name):
    """Descriptor-relative traversal, never follow a directory symlink."""
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        st = os.fstat(fd)
        _require(st.st_uid == os.getuid() and stat.S_IMODE(st.st_mode) == 0o700,
                 "PRIVATE_DIRECTORY_REQUIRED")
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def _snapshot(root):
    """Shared nonblocking lock compatible with A03's exclusive lock.

    Legacy writers are not covered. Explicit operator quiescence is still
    required. Compare root identity and directory/file identities at exit.
    """
    fd = _owner_dir(root)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InspectionError("COOPERATING_WRITER_BUSY") from None
        yield fd
        current = _owner_dir(root)
        try:
            _require(_dir_identity(current) == _dir_identity(fd), "STORE_ROOT_CHANGED")
        finally:
            os.close(current)
    finally:
        os.close(fd)


@contextmanager
def _child(parent, name):
    fd = _open_child(parent, name)
    try:
        yield fd
        st = os.stat(name, dir_fd=parent, follow_symlinks=False)
        _require(stat.S_ISDIR(st.st_mode) and
                 (st.st_dev, st.st_ino) == _dir_identity(fd), "STORE_DIRECTORY_CHANGED")
    finally:
        os.close(fd)


def _read(fd, name, limit):
    """Use the existing bounded private-file reader and retain its identity."""
    before = os.stat(name, dir_fd=fd, follow_symlinks=False)
    raw = _read_private_file(fd, name, limit)
    after = os.stat(name, dir_fd=fd, follow_symlinks=False)
    _require(_fingerprint(before) == _fingerprint(after), "FILE_CHANGED_DURING_READ")
    return raw, _fingerprint(after)


def _still_same(fd, name, identity):
    _require(_fingerprint(os.stat(name, dir_fd=fd, follow_symlinks=False)) == identity,
             "FILE_CHANGED_DURING_READ")


def _manifest(raw, observation_id):
    env = _decode(raw, MAX_ENVELOPE_BYTES)
    ref = unverified_ref_from_envelope(env)
    _require(ref["observation_id"] == observation_id, "OBSERVATION_ID_MISMATCH")
    digest = ref["payload_sha256_hex"]
    _require(env["evidence"]["payload_ref_str"] ==
             f"payloads/{digest[:2]}/{digest}.bin", "NONCANONICAL_PAYLOAD_REF")
    return env, digest, ref["payload_size_bytes"]


def _verify_content(env, raw, payload, observation_id, digest, size):
    _require(len(payload) == size and hmac.compare_digest(_sha(payload), digest),
             "PAYLOAD_HASH_OR_SIZE_MISMATCH")
    schema = env["schema_ref_str"]
    if schema == GENERIC_SCHEMA:
        row = _decode(payload, MAX_SAMPLE_BYTES)
        validate_sample(row)
        _require(canonical_json(row) == payload, "NONCANONICAL_GENERIC_PAYLOAD")
        expected = envelope_from_sample(row, digest, f"payloads/{digest[:2]}/{digest}.bin", size)
        _require(canonical_json(expected) == canonical_json(env),
                 "GENERIC_ENVELOPE_COMMITMENT_MISMATCH")
        state = "GENERIC_CONTENT_MATCHED"
    elif schema == CAMERA_SCHEMA:
        # UUID identifies the legacy record but does not commit to metadata.
        state = "LEGACY_ENVELOPE_UNBOUND"
    else:
        raise InspectionError("UNSUPPORTED_ENVELOPE")
    checkpoint = IntegrityCheckpoint(observation_id, schema, _sha(raw), len(raw), digest, size)
    return state, checkpoint


def verify_selected(root: Path, observation_id: str, *,
                    expected_checkpoint_sha256: str | None = None,
                    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
                    max_envelope_bytes: int = MAX_ENVELOPE_BYTES) -> IntegrityReport:
    """Inspect one explicitly selected record as a trusted offline store owner.

    No media or reference issuance. An independently retained checkpoint hash
    can establish equality to that checkpoint only, never historical capture.
    No full archive scan. No production ACL bypass is authorized by this API.
    """
    try:
        _require(type(observation_id) is str and _ID.fullmatch(observation_id),
                 "INVALID_OBSERVATION_ID")
        _require(expected_checkpoint_sha256 is None or
                 (type(expected_checkpoint_sha256) is str and _SHA.fullmatch(expected_checkpoint_sha256)),
                 "INVALID_EXPECTED_CHECKPOINT")
        _require(_limit(max_payload_bytes, MAX_PAYLOAD_BYTES) and
                 _limit(max_envelope_bytes, MAX_ENVELOPE_BYTES), "INVALID_INSPECTION_LIMIT")
        with _snapshot(Path(root)) as root_fd:
            with _child(root_fd, "observations") as obs_fd:
                name = observation_id + ".json"
                raw, env_identity = _read(obs_fd, name, max_envelope_bytes)
                env, digest, size = _manifest(raw, observation_id)
                _require(size <= max_payload_bytes, "PAYLOAD_BYTE_LIMIT")
                with _child(root_fd, "payloads") as payloads_fd:
                    with _child(payloads_fd, digest[:2]) as bucket_fd:
                        payload_name = digest + ".bin"
                        payload, payload_identity = _read(bucket_fd, payload_name, max_payload_bytes)
                        state, checkpoint = _verify_content(env, raw, payload, observation_id, digest, size)
                        # Re-read both selected files, not the entire store.
                        raw2, env2 = _read(obs_fd, name, max_envelope_bytes)
                        payload2, payload2_id = _read(bucket_fd, payload_name, max_payload_bytes)
                        _require(raw2 == raw and payload2 == payload and env2 == env_identity
                                 and payload2_id == payload_identity, "FILE_CHANGED_DURING_READ")
                        _still_same(obs_fd, name, env_identity)
                        _still_same(bucket_fd, payload_name, payload_identity)
            if expected_checkpoint_sha256 is not None:
                _require(hmac.compare_digest(checkpoint.sha256, expected_checkpoint_sha256),
                         "CHECKPOINT_MISMATCH")
        return IntegrityReport("CHECKED", "SELECTED_CONTENT_CHECKED",
            envelope_integrity=state, payload_integrity="HASH_AND_SIZE_MATCHED",
            checkpoint_status=("MATCHED_SUPPLIED_CHECKPOINT" if expected_checkpoint_sha256 is not None
                               else "NEW_BASELINE_ONLY"), checkpoint=checkpoint)
    except InspectionError as exc:
        reason = str(exc)
        if reason == "COOPERATING_WRITER_BUSY":
            return IntegrityReport("BUSY", reason)
        if reason == "CHECKPOINT_MISMATCH":
            return IntegrityReport("REJECTED", reason, checkpoint_status="MISMATCH")
        if reason in ("FILE_CHANGED_DURING_READ", "STORE_ROOT_CHANGED", "STORE_DIRECTORY_CHANGED"):
            return IntegrityReport("UNSTABLE", reason)
        return IntegrityReport("REJECTED", reason)
    except FileNotFoundError:
        return IntegrityReport("UNAVAILABLE", "SELECTED_FILE_MISSING")
    except IntakeError as exc:
        if str(exc) == "FILE_CHANGED_DURING_READ":
            return IntegrityReport("UNSTABLE", "FILE_CHANGED_DURING_READ")
        return IntegrityReport("REJECTED", "PRIVATE_FILE_OR_BYTE_LIMIT_REJECTED")
    except (BindingError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return IntegrityReport("REJECTED", "INVALID_OR_UNSUPPORTED_CONTENT")
    except (OSError, RuntimeError):
        return IntegrityReport("UNAVAILABLE", "LOCAL_INSPECTION_UNAVAILABLE")


def _inventory(root_fd, max_entries, max_bytes):
    """Bounded namespace-only census of legacy observation/payload references.

    An incomplete or invalid census yields no orphan candidates. Never checks
    derivative stores, external replicas or physical data availability.
    """
    count = total = 0
    referenced, present = set(), set()

    def names(fd):
        nonlocal count
        result = []
        with os.scandir(fd) as entries:
            for entry in entries:
                count += 1
                _require(count <= max_entries, "INVENTORY_ENTRY_LIMIT")
                result.append(entry.name)
        return sorted(result)

    def scan_observations(fd):
        nonlocal total
        before = _fingerprint(os.fstat(fd))
        for name in names(fd):
            _require(name.endswith(".json") and _ID.fullmatch(name[:-5]),
                     "UNEXPECTED_OBSERVATION_ENTRY")
            raw, identity = _read(fd, name, min(MAX_ENVELOPE_BYTES, max_bytes-total))
            total += len(raw)
            _require(total <= max_bytes, "INVENTORY_BYTE_LIMIT")
            _, digest, _ = _manifest(raw, name[:-5])
            referenced.add(digest)
            _still_same(fd, name, identity)
        _require(before == _fingerprint(os.fstat(fd)), "INVENTORY_CHANGED")

    def scan_payloads(fd):
        before = _fingerprint(os.fstat(fd))
        for bucket in names(fd):
            _require(_BUCKET.fullmatch(bucket), "UNEXPECTED_PAYLOAD_BUCKET")
            with _child(fd, bucket) as child:
                stamp = _fingerprint(os.fstat(child))
                for name in names(child):
                    digest = name[:-4]
                    _require(name.endswith(".bin") and _SHA.fullmatch(digest)
                             and digest[:2] == bucket, "UNEXPECTED_PAYLOAD_ENTRY")
                    info = os.stat(name, dir_fd=child, follow_symlinks=False)
                    _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                             and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1,
                             "PRIVATE_REGULAR_FILE_REQUIRED")
                    present.add(digest)
                _require(stamp == _fingerprint(os.fstat(child)), "INVENTORY_CHANGED")
        _require(before == _fingerprint(os.fstat(fd)), "INVENTORY_CHANGED")

    with _child(root_fd, "observations") as obs_fd:
        with _child(root_fd, "payloads") as payload_fd:
            # Repeat census under same cooperating-reader lock. This detects
            # observed change, not a proof against an uncooperative same-UID writer.
            scan_observations(obs_fd)
            scan_payloads(payload_fd)
            first = (set(referenced), set(present))
            observed_count = count
            referenced.clear()
            present.clear()
            scan_observations(obs_fd)
            scan_payloads(payload_fd)
            _require(first == (referenced, present), "INVENTORY_CHANGED")
            orphan = tuple(sorted(present - referenced))
            missing = tuple(sorted(referenced - present))
            # Unique digest count differs from number of observation manifests.
            return InventoryReport("COMPLETE_CANDIDATE_CENSUS", "LOCAL_NAMESPACE_ONLY",
                examined_entries=count, observation_manifests=len(names(obs_fd)),
                payload_files=len(present), candidate_orphan_count=len(orphan),
                missing_payload_count=len(missing), candidate_orphan_digests=orphan,
                missing_payload_digests=missing)


def audit_inventory(root: Path, *, max_entries: int = MAX_INVENTORY_ENTRIES,
                    max_manifest_bytes: int = MAX_INVENTORY_BYTES) -> InventoryReport:
    """Report candidate orphans, never safe-to-delete records.

    Budgets include repeated enumeration and manifest reads. Unsupported
    names, incomplete scan, missing directories, errors: no orphan list.
    """
    try:
        _require(_limit(max_entries, MAX_INVENTORY_ENTRIES)
                 and _limit(max_manifest_bytes, MAX_INVENTORY_BYTES), "INVALID_INVENTORY_LIMIT")
        with _snapshot(Path(root)) as root_fd:
            result = _inventory(root_fd, max_entries, max_manifest_bytes)
        return result
    except InspectionError as exc:
        return InventoryReport("INCOMPLETE", str(exc))
    except (IntakeError, BindingError, OSError, RuntimeError, ValueError,
            TypeError, KeyError, OverflowError, RecursionError):
        return InventoryReport("INCOMPLETE", "LOCAL_CENSUS_REJECTED_OR_UNAVAILABLE")
