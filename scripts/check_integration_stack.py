#!/usr/bin/env python3
"""Check the immutable reviewed RI stack; no network or device access.

This is an engineering drift check, NOT validation of a remote CI result,
approval, installation, authorization, or hardware readiness.
"""
from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "docs/integration/stack-review-2026-11-28.json"
TOP = "60c41b333527dfed6205d4bf0bae4926a6e3bae3"
ORIGINAL = "5372f758df79c93fc887f3858d878635447f4a4d"
EXPECTED = (4, 7, 8, 9, 10, 11, 12, 13)
SCHEMA = "contracts/consumer-observation-ref.v0.1-candidate.schema.json"
SCHEMA_BLOB = "3d92e074e71593bf6db0a735394c628ea131668d"

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, timeout=20)

def require(ok, message):
    if not ok:
        raise ValueError(message)

def tree(commit):
    result = {}
    for item in git("ls-tree", "-r", "-z", commit).split(b"\0"):
        if item:
            meta, path = item.split(b"\t", 1)
            result[path] = meta
    return result

def check():
    data = json.loads(SNAPSHOT.read_bytes())
    require(data["reviewed_stack_head"] == TOP, "reviewed stack pin changed")
    require(all(data[k] is False for k in ("normative", "physical_commissioning",
                                            "deployment_authorized")), "authority escalation")
    stack = data["stack"]
    require(tuple(s["pr"] for s in stack) == EXPECTED, "stack order changed")
    require(stack[0]["head"] == ORIGINAL and stack[-1]["head"] == TOP, "baseline changed")
    for i, step in enumerate(stack):
        require(step["state_at_review"] == "open_draft", "historic state changed")
        if i:
            require(step["base"] == stack[i-1]["head"], "stack dependency mismatch")
        git("merge-base", "--is-ancestor", step["base"], step["head"])
        git("merge-base", "--is-ancestor", step["head"], "HEAD")
        if i:
            before, after = tree(step["base"]), tree(step["head"])
            require(all(after.get(p) == meta for p, meta in before.items()),
                    "historical stack step changed existing files")
    before, after = tree(TOP), tree("HEAD")
    require(all(after.get(p) == meta for p, meta in before.items()),
            "consolidation changed reviewed stack files")
    require(git("hash-object", SCHEMA).decode().strip() == SCHEMA_BLOB, "schema pin mismatch")
    # Also ensure working tree bytes match tracked HEAD. Untracked local data is
    # outside the Git snapshot and must not be included in any pilot artifact.
    git("diff", "--exit-code", "HEAD", "--")
    require(len(data["reviewed_stack_ci"]) == 8 and
            all(c["head"] == TOP and c["conclusion"] == "success"
                for c in data["reviewed_stack_ci"]), "recorded CI head mismatch")
    return {"status":"REVIEWED_STACK_UNCHANGED","stack_steps":len(stack),
            "preserved_files":len(before), "remote_ci_verified_by_checker":False,
            "physical_authorized":False}

if __name__ == "__main__":
    print(json.dumps(check(), sort_keys=True))
