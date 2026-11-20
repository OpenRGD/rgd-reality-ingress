"""Local content-addressed evidence store with write-once observation envelopes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .model import observation_envelope

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class IntegrityError(RuntimeError):
    pass


def _atomic_create(path: Path, data: bytes) -> bool:
    """Atomically publish bytes, never overwrite an existing path."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_path = tempfile.mkstemp(prefix=".incoming-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as writer:
            writer.write(data)
            writer.flush()
            os.fsync(writer.fileno())
        try:
            os.link(temp_path, path)  # atomic, fails if target exists
            created = True
        except FileExistsError:
            created = False
        if created:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        return created
    finally:
        Path(temp_path).unlink(missing_ok=True)


class EvidenceStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.payloads = self.root / "payloads"
        self.observations = self.root / "observations"
        self.payloads.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.observations.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _payload_path(self, digest: str) -> Path:
        if not SHA256_RE.fullmatch(digest):
            raise IntegrityError("Invalid SHA-256 hex string")
        return self.payloads / digest[:2] / f"{digest}.bin"

    def put_payload(self, data: bytes) -> tuple[str, str]:
        digest = hashlib.sha256(data).hexdigest()
        path = self._payload_path(digest)
        if not _atomic_create(path, data):
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise IntegrityError(f"Existing payload mismatch: {path}")
        return digest, str(path.relative_to(self.root))

    def record(
        self,
        *,
        data: bytes,
        source_id: str,
        modality: str,
        reference_frame_id: str,
        sequence: int,
        timestamp: dict[str, Any],
        media_type: str,
        representation: dict[str, Any],
    ) -> dict[str, Any]:
        digest, relative_ref = self.put_payload(data)
        envelope = observation_envelope(
            source_id=source_id,
            source_modality=modality,
            reference_frame_id=reference_frame_id,
            sequence=sequence,
            payload_sha256=digest,
            payload_ref=relative_ref,
            payload_media_type=media_type,
            payload_size_bytes=len(data),
            timestamp=timestamp,
            representation=representation,
        )
        serial = json.dumps(envelope, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        path = self.observations / f"{envelope['observation_id_str']}.json"
        if not _atomic_create(path, serial):
            raise IntegrityError(f"Observation ID already exists: {path.name}")
        return envelope

    def get_observation(self, observation_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"obs_[0-9a-f]{32}", observation_id):
            raise IntegrityError("Invalid observation ID")
        file_path = self.observations / f"{observation_id}.json"
        return json.loads(file_path.read_text(encoding="utf-8"))

    def verify(self) -> dict[str, Any]:
        """Validate payload hashes referenced by each manifest, not Chronon claims."""
        errors = []
        seen = set()
        files = sorted(self.observations.glob("obs_*.json"))
        for path in files:
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                obs_id = envelope["observation_id_str"]
                if path.name != obs_id + ".json":
                    raise IntegrityError("ID/path mismatch")
                if obs_id in seen:
                    raise IntegrityError("Duplicate observation ID")
                seen.add(obs_id)
                if envelope.get("schema_ref_str") == "urn:openrgd:experimental:reality-ingress:generic-observation:v0":
                    from .generic import verify_generic_envelope
                    verify_generic_envelope(envelope)
                evidence = envelope["evidence"]
                digest = evidence["payload_sha256_hex_str"]
                payload_path = self._payload_path(digest)
                if evidence["payload_ref_str"] != str(payload_path.relative_to(self.root)):
                    raise IntegrityError("Noncanonical payload ref")
                if not payload_path.is_file():
                    raise IntegrityError("Missing payload")
                blob = payload_path.read_bytes()
                if hashlib.sha256(blob).hexdigest() != digest:
                    raise IntegrityError("Payload hash mismatch")
                if evidence["payload_size_bytes_uint"] != len(blob):
                    raise IntegrityError("Payload length mismatch")
                if envelope.get("schema_ref_str") == "urn:openrgd:experimental:reality-ingress:generic-observation:v0":
                    from .generic import envelope_from_sample, validate_sample
                    row = json.loads(blob.decode("utf-8"))
                    validate_sample(row)
                    expected = envelope_from_sample(
                        row, digest, evidence["payload_ref_str"], len(blob))
                    if expected != envelope:
                        raise IntegrityError("Generic observation does not match committed source sample")
            except (ValueError, KeyError, OSError, IntegrityError, TypeError, UnicodeError) as exc:
                errors.append({"observation_file": path.name, "error": str(exc)})
        from .derivations import DerivationStore
        derived = DerivationStore(self).verify()
        from .fiducials import FiducialStore
        fiducials = FiducialStore(self).verify()
        errors.extend(derived["derivation_errors"])
        errors.extend(fiducials["fiducial_errors"])
        status = "FAIL" if errors else ("PASS" if files else "EMPTY")
        return {
            "status": status,
            "observation_count": len(files),
            "unique_payload_count": len(list(self.payloads.glob("*/*.bin"))),
            "derivation_count": derived["derivation_count"],
            "referenced_observation_count": derived["referenced_observation_count"],
            "fiducial_derivation_count": fiducials["fiducial_derivation_count"],
            "fiducial_referenced_observations": fiducials["fiducial_referenced_observations"],
            "errors": errors,
        }
