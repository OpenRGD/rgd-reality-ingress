"""RI-A03: explicitly requested, bounded offline IMU spool intake.

Linux local private directories, quiescent legacy EvidenceStore, no hardware,
network, auth service, media ingestion, history, automatic retries or cleanup.
No changes to v0.4 record IDs, encoding, or existing CLI.
"""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from uuid import UUID

from .consumer_ref import unverified_ref_from_envelope
from .evidence import EvidenceStore, IntegrityError
from .generic import canonical_json, envelope_from_sample, record_sample, validate_sample
from .interop_numeric import require_u64, NumericDomainError
from .session_binding import BindingError, SuppliedEvidence, _decode, resolve_session

PROFILE = "ri.imu-completed-spool.v0.1-candidate"
MAX_ROWS = 60
MAX_LINE_BYTES = 4096  # includes LF
MAX_SPOOL_BYTES = 256 * 1024
MAX_PLANNED_WRITE_BYTES = 512 * 1024
PRODUCERS = frozenset({
    "paky-01/imu_publish.py:IMU-RI-01-candidate",
    "rgd-imu/0.1.0a4:IMU-FOUNDATION-01D-candidate",
})
GENERALIZED = "rgd-imu/0.1.0a4:IMU-FOUNDATION-01D-candidate"
_SOURCE_KEYS = frozenset({"source_id_str", "modality_str", "reference_frame_id_str",
                          "sample_sequence_uint", "session_id_str"})
_STAMP_KEYS = frozenset({"received_monotonic_ns", "received_unix_estimate_ns",
                         "host_wall_pair_span_ns", "clock_domain_ref",
                         "receive_timestamp_method", "source_time", "source_time_status_str"})
_SAMPLE_KEYS = frozenset({"schema_version", "robot_id", "sensor_id", "source_id",
                         "sensor_frame_id", "session_id", "sequence", "host_receive_utc",
                         "host_monotonic_ns", "acceleration_m_s2", "angular_velocity_rad_s",
                         "orientation_euler_deg", "temperature_c", "calibration_revision"})
_WRAPPER_KEYS = frozenset({"console_ingest_sample", "console_delivery_status",
    "source_kind_claim", "source_verified", "robot_binding_verified", "reference_frame",
    "quality", "calibration_revision", "heading_calibrated", "decision_eligible",
    "observation_only", "history_committed", "actuation_enabled"})
_EXTRA_KEYS = frozenset({"assembly_policy", "component_receipt_ages_ns",
                         "host_receipt_span_ns", "synchronized"})


class IntakeError(ValueError):
    """Stable diagnostic code; never includes source content or local paths."""


def _require(condition, code):
    if not condition:
        raise IntakeError(code)


def _uint(value):
    try:
        return require_u64(value)
    except NumericDomainError:
        raise IntakeError("OUTSIDE_NATIVE_U64_DOMAIN") from None


@dataclass(frozen=True)
class IntakeLimits:
    max_rows: int = MAX_ROWS
    max_line_bytes: int = MAX_LINE_BYTES
    max_spool_bytes: int = MAX_SPOOL_BYTES
    max_planned_write_bytes: int = MAX_PLANNED_WRITE_BYTES

    def __post_init__(self):
        for value, ceiling in zip(
            (self.max_rows, self.max_line_bytes, self.max_spool_bytes,
             self.max_planned_write_bytes),
            (MAX_ROWS, MAX_LINE_BYTES, MAX_SPOOL_BYTES, MAX_PLANNED_WRITE_BYTES),
        ):
            _require(type(value) is int and 0 < value <= ceiling, "INVALID_LIMIT")


def _label(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", value) is not None


@dataclass(frozen=True)
class SourceScope:
    """Operator-selected exact source labels; not authenticated identities."""
    producer: str
    robot_id: str
    sensor_id: str
    source_id: str
    frame_id: str
    session_id: str
    boot_id: str

    def __post_init__(self):
        _require(type(self.producer) is str and self.producer in PRODUCERS,
                 "UNSUPPORTED_PRODUCER_PROFILE")
        _require(all(_label(v) for v in (self.robot_id, self.sensor_id,
                 self.source_id, self.frame_id)), "INVALID_SOURCE_SCOPE")
        _require(type(self.session_id) is str and
                 re.fullmatch(r"[0-9a-f]{32}", self.session_id) is not None and
                 self.session_id != "0" * 32, "INVALID_SESSION")
        try:
            boot = UUID(self.boot_id)
            _require(str(boot) == self.boot_id and boot.int != 0, "INVALID_BOOT")
        except (ValueError, TypeError, AttributeError):
            raise IntakeError("INVALID_BOOT") from None

    @property
    def filename(self):
        return "imu-" + self.session_id + ".jsonl"


@dataclass(frozen=True)
class PreparedRecord:
    line: int
    payload: bytes
    envelope: bytes
    observation_id: str
    digest: str


@dataclass(frozen=True)
class IntakeReport:
    status: str
    reason: str
    spool_sha256: str | None = None
    input_bytes: int = 0
    input_rows: int = 0
    unique_rows: int = 0
    duplicate_rows: int = 0
    planned_write_bytes: int = 0
    created: int = 0
    already_present: int = 0
    completed: int = 0
    failed_line: int | None = None
    # No proof of source, consent, complete archive, freshness or authority.
    source_verified: bool = False
    robot_binding_verified: bool = False
    history_committed: bool = False
    actuation_enabled: bool = False


def _owner_dir(path: Path):
    _require(path.is_absolute() and path.resolve(strict=True) == path,
             "NONCANONICAL_DIRECTORY")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        _require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                 "PRIVATE_DIRECTORY_REQUIRED")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_uid, info.st_nlink)


def _read_private_file(dir_fd, name, limit, *, missing_ok=False):
    try:
        listed = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        _require(stat.S_ISREG(listed.st_mode), "PRIVATE_REGULAR_FILE_REQUIRED")
        fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=dir_fd)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    try:
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                 and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1,
                 "PRIVATE_REGULAR_FILE_REQUIRED")
        _require(_fingerprint(listed) == _fingerprint(before), "FILE_CHANGED_DURING_READ")
        _require(before.st_size <= limit, "FILE_BYTE_LIMIT")
        chunks = bytearray()
        while len(chunks) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        _require(len(chunks) <= limit, "FILE_BYTE_LIMIT")
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        _require(_fingerprint(before) == _fingerprint(after) == _fingerprint(named)
                 and len(chunks) == before.st_size, "FILE_CHANGED_DURING_READ")
        return bytes(chunks)
    finally:
        os.close(fd)


def _completion(report, scope, limits):
    _require(type(report) is dict and report.get("state") == "COMPLETED"
             and report.get("filename") == scope.filename
             and report.get("history_committed") is False
             and report.get("actuation_enabled") is False
             and report.get("error_class") is None and report.get("error_code") is None,
             "COMPLETION_REPORT_REQUIRED")
    count = report.get("written")
    _require(type(count) is int and 0 < count <= limits.max_rows,
             "COMPLETION_COUNT_INVALID")
    _require(type(report.get("enqueued")) is int
             and report["enqueued"] == count, "COMPLETION_COUNT_INVALID")
    if "written_bytes" in report:
        n = report["written_bytes"]
        _require(type(n) is int and 0 < n <= limits.max_spool_bytes,
                 "COMPLETION_BYTES_INVALID")


def _read_spool(directory, scope, report, limits):
    _completion(report, scope, limits)
    fd = _owner_dir(Path(directory))
    try:
        def no_part():
            try:
                os.stat(scope.filename + ".part", dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            raise IntakeError("PART_FILE_PRESENT")
        no_part()
        raw = _read_private_file(fd, scope.filename, limits.max_spool_bytes)
        no_part()
    finally:
        os.close(fd)
    _require(raw and raw.endswith(b"\n"), "UNTERMINATED_OR_EMPTY_SPOOL")
    if "written_bytes" in report:
        _require(report["written_bytes"] == len(raw), "COMPLETION_BYTES_MISMATCH")
    return raw


def _keys(value, keys):
    return type(value) is dict and set(value) == keys


def _vector(value):
    return (type(value) is list and len(value) == 3 and
            all(type(x) in (int, float) and math.isfinite(x) for x in value))


def _validate_row(row, scope):
    _require(_keys(row, {"schema_ref_str", "producer_str", "source",
                         "temporal_binding", "payload"}), "UNSUPPORTED_ROW_SHAPE")
    validate_sample(row)
    source, stamp, wrapper = row["source"], row["temporal_binding"], row["payload"]
    _require(_keys(source, _SOURCE_KEYS) and _keys(stamp, _STAMP_KEYS),
             "UNSUPPORTED_SOURCE_OR_TIME_SHAPE")
    _require(row["producer_str"] == scope.producer and
             (source["source_id_str"], source["modality_str"],
              source["reference_frame_id_str"], source["session_id_str"]) ==
             (scope.source_id, "imu", scope.frame_id, scope.session_id),
             "SOURCE_SCOPE_MISMATCH")
    seq = _uint(source["sample_sequence_uint"])
    for field in ("received_monotonic_ns", "received_unix_estimate_ns",
                  "host_wall_pair_span_ns"):
        _uint(stamp[field])
    _require(seq > 0 and stamp["received_monotonic_ns"] > 0
             and stamp["host_wall_pair_span_ns"] <= 50_000_000, "RECEIPT_PROFILE_MISMATCH")
    domain = {"clock_domain_id_str": "chronos.monotonic.boot:" + scope.boot_id,
              "layer_enum_str": "CHRONOS", "clock_kind_enum_str": "MONOTONIC",
              "epoch_ref_str": "linux-boot:" + scope.boot_id,
              "timescale_enum_str": "MONOTONIC", "boot_id_str": scope.boot_id}
    _require(stamp["clock_domain_ref"] == domain and stamp["source_time"] is None
             and stamp["receive_timestamp_method"] == "userspace_after_existing_WIT_serial_read",
             "RECEIPT_PROFILE_MISMATCH")
    allowed = _WRAPPER_KEYS | (_EXTRA_KEYS if scope.producer == GENERALIZED else frozenset())
    _require(_keys(wrapper, allowed), "UNSUPPORTED_IMU_REPRESENTATION")
    _require(wrapper["console_delivery_status"] == "accepted_http_202"
             and wrapper["source_kind_claim"] == "physical"
             and wrapper["quality"] == "unverified"
             and wrapper["reference_frame"] == "imu_sensor_axes_unverified",
             "UNSUPPORTED_IMU_QUALITY")
    sample = wrapper["console_ingest_sample"]
    _require(_keys(sample, _SAMPLE_KEYS) and
             (sample["robot_id"], sample["sensor_id"]) == (scope.robot_id, scope.sensor_id)
             and sample["calibration_revision"] is None
             and type(sample["host_receive_utc"]) is str
             and 0 < len(sample["host_receive_utc"]) <= 64,
             "UNSUPPORTED_ORIGINAL_SAMPLE")
    _uint(sample["sequence"])
    _uint(sample["host_monotonic_ns"])
    _require(all(_vector(sample[k]) for k in
                 ("acceleration_m_s2", "angular_velocity_rad_s", "orientation_euler_deg")),
             "INVALID_MEASUREMENT_VECTOR")
    temp = sample["temperature_c"]
    _require(temp is None or (type(temp) in (int, float) and math.isfinite(temp)),
             "INVALID_TEMPERATURE")
    if scope.producer == GENERALIZED:
        ages = wrapper["component_receipt_ages_ns"]
        _require(wrapper["assembly_policy"] in ("legacy-reuse-within-window", "strict-no-reuse")
                 and wrapper["synchronized"] is False
                 and _keys(ages, {"acceleration", "angular_velocity", "vendor_euler"}),
                 "UNSUPPORTED_ASSEMBLY_PROFILE")
        for age in ages.values():
            _uint(age)
        _uint(wrapper["host_receipt_span_ns"])
    payload = canonical_json(row)
    digest = hashlib.sha256(payload).hexdigest()
    env = envelope_from_sample(row, digest, f"payloads/{digest[:2]}/{digest}.bin", len(payload))
    # A02 already validates duplicated source fields, authority flags and exact
    # envelope commitment. This internal projection is never issued to a consumer.
    ref = unverified_ref_from_envelope(env)
    binding = resolve_session(SuppliedEvidence(canonical_json(ref), canonical_json(env), payload))
    _require(binding.status == "CONTENT_MATCHED", "SOURCE_CONTENT_BINDING_REJECTED")
    encoded = json.dumps(env, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    return seq, stamp["received_monotonic_ns"], payload, digest, env["observation_id_str"], encoded


def _prepare(raw, scope, report, limits):
    lines = raw[:-1].split(b"\n")
    _require(len(lines) == report["written"] and len(lines) <= limits.max_rows,
             "COMPLETION_COUNT_MISMATCH")
    unique = {}
    obs_ids = {}
    seen = {}
    last_seq, last_mono = -1, -1
    payload_total = 0
    for number, line in enumerate(lines, 1):
        _require(bool(line) and not line.endswith(b"\r")
                 and len(line) + 1 <= limits.max_line_bytes, "LINE_BYTE_OR_FORMAT_LIMIT")
        try:
            row = _decode(line, limits.max_line_bytes)
            seq, mono, payload, digest, obs_id, encoded = _validate_row(row, scope)
        except IntakeError:
            raise
        except (BindingError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
            raise IntakeError("INVALID_SOURCE_RECORD") from None
        _require(len(payload) <= limits.max_line_bytes, "CANONICAL_ROW_BYTE_LIMIT")
        payload_total += len(payload)
        _require(payload_total <= limits.max_spool_bytes, "CANONICAL_SPOOL_BYTE_LIMIT")
        if seq in seen:
            _require(seen[seq] == (obs_id, digest), "SESSION_SEQUENCE_CONFLICT")
            continue
        _require(seq > last_seq and mono >= last_mono, "SOURCE_ORDER_CONFLICT")
        _require(obs_id not in obs_ids, "OBSERVATION_ID_COLLISION")
        seen[seq] = (obs_id, digest)
        obs_ids[obs_id] = digest
        unique[seq] = PreparedRecord(number, payload, encoded, obs_id, digest)
        last_seq, last_mono = seq, mono
    records = tuple(unique.values())
    # Worst-case new content + manifests, independent of u64 type bounds and
    # current store size. Filesystem allocation/metadata overhead is excluded.
    write_bytes = sum(len(r.payload) + len(r.envelope) for r in records)
    _require(write_bytes <= limits.max_planned_write_bytes, "PLANNED_WRITE_BYTE_LIMIT")
    return records, IntakeReport("PREVIEW", "VALIDATED_NOT_WRITTEN", hashlib.sha256(raw).hexdigest(),
                                 len(raw), len(lines), len(records), len(lines)-len(records),
                                 write_bytes)


def _load(directory, scope, report, limits):
    _require(type(scope) is SourceScope and type(limits) is IntakeLimits, "INVALID_CONFIGURATION")
    _require(type(report) is dict, "COMPLETION_REPORT_REQUIRED")
    report = dict(report)
    raw = _read_spool(directory, scope, report, limits)
    return _prepare(raw, scope, report, limits)


def preview_spool(directory, scope: SourceScope, completion_report: dict,
                  *, limits: IntakeLimits = IntakeLimits()) -> IntakeReport:
    """Full preflight without opening or creating an EvidenceStore."""
    try:
        _, summary = _load(directory, scope, completion_report, limits)
        return summary
    except IntakeError as exc:
        return IntakeReport("REJECTED", str(exc))
    except (OSError, ValueError, TypeError, RuntimeError):
        return IntakeReport("REJECTED", "SPOOL_UNAVAILABLE_OR_INVALID")


def _existing(path: Path, expected: bytes):
    # All path components are derived from the trusted store and digests, never
    # caller-controlled payload_ref. The operator must quiesce legacy writers.
    try:
        fd = _owner_dir(path.parent)
    except FileNotFoundError:
        return False
    try:
        data = _read_private_file(fd, path.name, len(expected), missing_ok=True)
        if data is None:
            return False
        _require(data == expected, "EXISTING_CONTENT_CONFLICT")
        return True
    finally:
        os.close(fd)


def _preflight_store(store, records):
    _require(type(store) is EvidenceStore and
             store.payloads == store.root / "payloads" and
             store.observations == store.root / "observations",
             "EXPLICIT_LEGACY_STORE_REQUIRED")
    for folder in (store.payloads, store.observations):
        fd = _owner_dir(folder)
        os.close(fd)
    for record in records:
        payload = _existing(store.payloads / record.digest[:2] / (record.digest + ".bin"),
                            record.payload)
        envelope = _existing(store.observations / (record.observation_id + ".json"),
                             record.envelope)
        _require(not envelope or payload, "EXISTING_OBSERVATION_MISSING_PAYLOAD")


def apply_spool(store: EvidenceStore, directory, scope: SourceScope, completion_report: dict,
                *, expected_spool_sha256: str, limits: IntakeLimits = IntakeLimits()) -> IntakeReport:
    """Explicit offline commit. Revalidate spool and compare prior preview hash.

    Per-record legacy atomic creation, NOT an atomic batch or power-loss
    transaction. A failure can leave an orphan payload or uncertain final
    record. Retry explicitly with identical bytes after inspection; no delete,
    auto-repair or automatic retry. The directory lock coordinates ONLY A03
    clients; other writers must be stopped by the operator.
    """
    from dataclasses import replace
    try:
        _require(type(expected_spool_sha256) is str and
                 re.fullmatch(r"[0-9a-f]{64}", expected_spool_sha256) is not None,
                 "PREVIEW_HASH_REQUIRED")
        records, result = _load(directory, scope, completion_report, limits)
        _require(result.spool_sha256 == expected_spool_sha256, "PREVIEW_HASH_MISMATCH")
        _require(type(store) is EvidenceStore, "EXPLICIT_LEGACY_STORE_REQUIRED")
        root_fd = _owner_dir(store.root)
    except IntakeError as exc:
        return IntakeReport("REJECTED", str(exc))
    except (OSError, ValueError, TypeError, RuntimeError):
        return IntakeReport("REJECTED", "SPOOL_OR_STORE_UNAVAILABLE")
    try:
        try:
            fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return replace(result, status="REJECTED", reason="INTAKE_BUSY")
        except OSError:
            return replace(result, status="REJECTED", reason="INTAKE_LOCK_UNAVAILABLE")
        try:
            _preflight_store(store, records)
        except IntakeError as exc:
            return replace(result, status="REJECTED", reason=str(exc))
        except (OSError, ValueError, TypeError, RuntimeError):
            return replace(result, status="REJECTED", reason="STORE_PREFLIGHT_FAILED")
        created = existing = 0
        for record in records:
            try:
                env, is_new = record_sample(store, json.loads(record.payload))
                _require(env["observation_id_str"] == record.observation_id and
                         (json.dumps(env, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")
                          + b"\n") == record.envelope, "COMMITTED_ENVELOPE_MISMATCH")
            except (OSError, ValueError, IntegrityError, TypeError, KeyError, RuntimeError):
                return replace(result, status="PARTIAL_OR_UNCERTAIN",
                               reason="RECORD_WRITE_NOT_CONFIRMED",
                               created=created, already_present=existing,
                               completed=created+existing, failed_line=record.line)
            created += int(is_new)
            existing += int(not is_new)
        return replace(result, status="IMPORTED", reason="RECORDS_CONFIRMED_NOT_ATTESTED",
                       created=created, already_present=existing, completed=created+existing)
    finally:
        os.close(root_fd)
