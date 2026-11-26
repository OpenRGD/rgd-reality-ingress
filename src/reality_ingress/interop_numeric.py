"""Proposed native integer compatibility profile for new RI interfaces.

Not a JSON Schema validator, store reader, attestation, access gate or
runtime policy. Existing v0.4 readers and v0.1 consumer references are
unchanged. Validate the owning schema and provenance separately.
"""
from __future__ import annotations

from collections.abc import Mapping

PROFILE = "ri.native-u64.v0.1-candidate"
MAX_U64 = (1 << 64) - 1
MAX_SAFE_JSON_NUMBER = (1 << 53) - 1


class NumericDomainError(ValueError):
    """A rejected numeric representation; never coerce or truncate it."""


def require_u64(value: object) -> int:
    """Accept only a native exact integer in the proposed lossless domain."""
    if type(value) is not int or not 0 <= value <= MAX_U64:
        raise NumericDomainError("OUTSIDE_NATIVE_U64_DOMAIN")
    return value


def check_ref_integer_domain(reference: Mapping) -> None:
    """Check three v0.1 reference counters only; not full schema acceptance.

    No mutation or reissuance. An old reference outside this proposed
    profile is not automatically invalid under its historical schema.
    """
    if not isinstance(reference, Mapping):
        raise NumericDomainError("MISSING_REFERENCE_COUNTER")
    try:
        counters = (
            reference["sample_sequence"], reference["payload_size_bytes"],
            reference["time"]["received_monotonic_ns"],
        )
    except (KeyError, TypeError):
        raise NumericDomainError("MISSING_REFERENCE_COUNTER") from None
    for value in counters:
        require_u64(value)


def fits_safe_json_number(value: object) -> bool:
    """Advisory only: can an exact u64 round-trip through binary64 integer range?

    False does not invalidate a native u64. No JS transport is implemented.
    """
    return require_u64(value) <= MAX_SAFE_JSON_NUMBER
