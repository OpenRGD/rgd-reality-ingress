#!/usr/bin/env python3
"""Validate the engineering registry and pinned local RI bytes, offline.

This is developer tooling, not an authorization or runtime compatibility gate.
No external repository checkout, network, devices or evidence data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = Path("docs/compatibility/registry.v0.1.json")
SCHEMA = Path("docs/compatibility/registry.v0.1.schema.json")
BASELINE = "5372f758df79c93fc887f3858d878635447f4a4d"
REF_PATH = "contracts/consumer-observation-ref.v0.1-candidate.schema.json"
REF_SHA = "3d92e074e71593bf6db0a735394c628ea131668d"
MAX_JSON = 256 * 1024
MAX_FILE = 4 * 1024 * 1024
EXPECTED_TARGETS = {f"RI-H{i:02d}" for i in range(1, 11)}
SCOPES = {
    "pinned_ri_implementation": "ri_conformance",
    "pinned_contract_fixture": "contract_fixture_conformance",
    "pinned_contract_boundary": "schema_boundary_conformance",
    "metadata_only": "metadata_conformance",
}


class RegistryError(ValueError):
    pass


def _unique_pairs(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise RegistryError("duplicate JSON object key")
        result[k] = v
    return result


def _reject_constant(value):
    raise RegistryError("non-finite JSON number")


def load_json(path: Path) -> Any:
    with path.open("rb") as f:
        raw = f.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON:
        raise RegistryError("manifest or schema exceeds JSON byte limit")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RegistryError("invalid registry JSON") from exc


def safe_path(path: str) -> bool:
    """Repository-relative POSIX path, not URL, device or traversal."""
    if not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_.\-/]+", path):
        return False
    p = PurePosixPath(path)
    return (not p.is_absolute() and path == p.as_posix()
            and all(part not in {".", "..", ".git"} for part in path.split("/"))
            and all(part for part in path.split("/")))


def frozen_scope(path: str) -> bool:
    return (path in {"pyproject.toml", REF_PATH}
            or path.startswith("src/reality_ingress/")
            or path.startswith("tests/"))


def git_blob_sha1(raw: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw,
        usedforsecurity=False,
    ).hexdigest()


def validate_registry(doc: dict, schema: dict) -> None:
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(doc), key=lambda e: str(list(e.path)))
    if errors:
        raise RegistryError("schema validation failed at " + "/".join(map(str, errors[0].path)))
    baseline = doc["baseline"]
    if baseline["commit"] != BASELINE or baseline["schema_git_blob_sha1"] != REF_SHA:
        raise RegistryError("v0.1 frozen baseline must not be repinned")
    paths = [f["path"] for f in baseline["frozen_files"]]
    if len(paths) != len(set(paths)):
        raise RegistryError("duplicate baseline path")
    if any(not safe_path(p) or not frozen_scope(p) for p in paths):
        raise RegistryError("invalid frozen file path")
    pins = {f["path"]: f["git_blob_sha1"] for f in baseline["frozen_files"]}
    if pins.get(REF_PATH) != REF_SHA or "pyproject.toml" not in pins:
        raise RegistryError("missing or altered core baseline pin")
    targets = doc["targets"]
    if {t["id"] for t in targets} != EXPECTED_TARGETS or len(targets) != 10:
        raise RegistryError("exactly ten unique original handoff targets required")
    seen_ids, seen_prs, seen_runs, seen_returns = set(), set(), set(), set()
    for target in targets:
        entries = target["integrations"]
        state = target["status"]
        if state in {"awaiting_return", "blocked_repo_pending"}:
            if entries:
                raise RegistryError("pending target cannot claim a returned integration")
            continue
        if not entries:
            raise RegistryError("received target requires a recorded return")
        if state == "review_only" and any(e["verification_kind"] != "documentary_review" for e in entries):
            raise RegistryError("documentary target cannot claim implementation")
        if state == "candidate_compatible" and all(e["verification_kind"] == "documentary_review" for e in entries):
            raise RegistryError("documentary review alone is not conformance")
        for entry in entries:
            eid, pr = entry["id"], (entry["repository"].lower(), entry["pull_request"])
            comment = entry["return_comment_id"]
            if eid in seen_ids or pr in seen_prs or comment in seen_returns:
                raise RegistryError("duplicate integration, owner PR or return")
            seen_ids.add(eid)
            seen_prs.add(pr)
            seen_returns.add(comment)
            artifacts = [a["path"] for a in entry["artifacts"]]
            if any(not safe_path(p) for p in artifacts) or len(set(artifacts)) != len(artifacts):
                raise RegistryError("unsafe or duplicate artifact path")
            kind = entry["verification_kind"]
            checks = entry["checks"]
            if kind == "documentary_review":
                if checks:
                    raise RegistryError("documentary review must not claim conformance runs")
                continue
            scope = SCOPES[kind]
            if not any(c["scope"] == scope and c["conclusion"] == "success" for c in checks):
                raise RegistryError("missing successful check for claimed scope")
            for c in checks:
                run = (entry["repository"].lower(), c["run_id"])
                if run in seen_runs:
                    raise RegistryError("duplicate CI run")
                seen_runs.add(run)
                if c["tested_commit"] != entry["commit"]:
                    raise RegistryError("CI head differs from owner revision")
                if c["scope"] not in {scope, "owner_checks"}:
                    raise RegistryError("CI scope exceeds declared verification class")


def verify_files(doc: dict, root: Path) -> int:
    count = 0
    for item in doc["baseline"]["frozen_files"]:
        rel = item["path"]
        if not safe_path(rel) or not frozen_scope(rel):
            raise RegistryError("unsafe baseline path")
        path = root
        for part in PurePosixPath(rel).parts:
            path = path / part
            if path.is_symlink():
                raise RegistryError("symlink in frozen path: " + rel)
        if not path.is_file():
            raise RegistryError("missing frozen file: " + rel)
        with path.open("rb") as f:
            raw = f.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE or git_blob_sha1(raw) != item["git_blob_sha1"]:
            raise RegistryError("frozen file drift: " + rel)
        count += 1
    return count


def verify_git_baseline(doc: dict, root: Path) -> None:
    """Compare the inventory to the immutable parent commit, not the mutable manifest."""
    try:
        raw = subprocess.check_output(
            ["git", "ls-tree", "-r", "-z", BASELINE], cwd=root,
            stderr=subprocess.PIPE, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RegistryError("frozen Git commit unavailable locally") from exc
    expected = {}
    for line in raw.split(b"\0"):
        if not line:
            continue
        meta, name = line.split(b"\t", 1)
        mode, kind, sha = meta.decode("ascii").split()
        path = name.decode("utf-8")
        if frozen_scope(path):
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise RegistryError("unexpected frozen Git object type")
            expected[path] = sha
    declared = {f["path"]: f["git_blob_sha1"] for f in doc["baseline"]["frozen_files"]}
    if expected != declared:
        raise RegistryError("frozen inventory differs from original Git tree")


def summary(doc: dict) -> dict:
    returned = [t for t in doc["targets"] if t["integrations"]]
    entries = [e for t in returned for e in t["integrations"]]
    checks = [c for e in entries for c in e["checks"]]
    return {
        "registry_status": "VALID_ENGINEERING_SNAPSHOT",
        "snapshot_date": doc["snapshot_date"],
        "handoffs_received": len(returned),
        "handoffs_total": len(doc["targets"]),
        "integration_records": len(entries),
        "ci_records": len(checks),
        "frozen_files": len(doc["baseline"]["frozen_files"]),
        "remote_ci_reexecuted": False,
        "normative": False,
        "runtime_authority": False,
        "physical_commissioning": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-baseline", action="store_true",
                        help="also compare the immutable local Git tree")
    args = parser.parse_args()
    try:
        doc, schema = load_json(ROOT / REGISTRY), load_json(ROOT / SCHEMA)
        validate_registry(doc, schema)
        verify_files(doc, ROOT)
        if args.git_baseline:
            verify_git_baseline(doc, ROOT)
    except (RegistryError, OSError) as exc:
        print("REGISTRY INVALID:", str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary(doc), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
