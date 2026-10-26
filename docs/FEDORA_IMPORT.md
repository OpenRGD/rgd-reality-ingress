# Fedora v0.4 intake — do not import blindly

**Source host**: Fedora development workstation.

**Known from operator inventory**:
`~/workspace/robotics/openrgd-reality-ingress-v0.1` through `v0.4`,
with ZIPs in `~/Downloads`, and editable v0.4 in the
`rgd-perception` Conda environment.

**Reported archive SHA-256 (must verify before trusting any copy):**
`4e88aef9999d8f12d57fac2b027eff58adf9a125ad1ccb2275e98e3936ffe81b`

## Intake order

1. Preserve original ZIPs as read-only archives; compare manifests v0.1–v0.4.
2. Audit the full v0.4 source and tests, including dependency/license metadata.
3. Review every file for secrets or PII, not just sensitive filenames.
4. Move source files, minimal synthetic tests, docs and project metadata only
   into a non-default branch.
5. Exclude `reality-evidence*`, `reality-v04-test`, raw video/audio,
   local DBs, devices and any private credentials.
6. Run tests before and after the import. Record successes *and* limitations.
7. Move model inference from Ingress to Perception without changing signed/raw
   observation identity; define explicit compatibility adapters for legacy data.
8. Propose PR, review and merge deliberately.

## Verification example (read-only on Fedora)

```bash
BASE="$HOME/workspace/robotics/openrgd-reality-ingress-v0.4"
sha256sum "$HOME/Downloads/openrgd-reality-ingress-v0.4.zip"
find "$BASE" -type f ! -path '*/__pycache__/*' | sort
cat "$BASE/pyproject.toml"
find "$BASE/tests" -type f -name 'test_*.py' -print
```

A filename-only scan is not proof that source contains no credentials.
Do not push on this information alone.
