# Pinned Aftermath skills

The contents of this directory are vendored **unedited** from upstream so the
next sync is a diff, not an archaeology exercise.

| field | value |
|---|---|
| repository | `https://github.com/AftermathFinance/skills` |
| branch | `feat/v2-skills` |
| commit | `5b614db62dcd2e58f442e93661f608fe7b073c32` |
| skill | `aftermath-perpetuals` |
| skill version | `3.0.0` |
| license | Apache-2.0 (see `LICENSE`) |
| vendored | 2026-07-28 |

The commit SHA is also stored machine-readably in `COMMIT`, which
`tools/validate_skills_contract.py` reads and `tests/test_skills_contract.py`
asserts against. The per-file SHA-256 digests are pinned in
`contracts/aftermath-skills-v3-contract.json` and
`aftermath-overlay/provenance.json`, and
`tests/test_vendored_skills.py` verifies the bytes on disk against them — so a
silent edit to a vendored file fails CI.

## Do not edit these files

They are a reference, not a source. Fixes belong upstream; the correction for
the one known defect (the retired host) is recorded in `README-DELTA.md` and
enforced by a test rather than by patching the vendored bytes.

## What is in scope

`tools/validate_skills_contract.py` classifies every vendored file:

| file | status |
|---|---|
| `skills/api/SKILL.md` | applied |
| `skills/api/ccxt.md` | applied |
| `skills/api/error-handling.md` | applied |
| `skills/api/gotchas.md` | applied |
| `skills/api/monitoring-patterns.md` | applied |
| `skills/api/native.md` | applied |
| `skills/api/safety-and-risk.md` | applied |
| everything else under `skills/api/` | out of scope |
| `skills/gas/` | out of scope for the classification, used as gas-model reference |

"Applied" means this repository's runtime is expected to *conform* to the file,
not merely cite it. The conformance points are covered by tests:

| skill rule | where it lives | test |
|---|---|---|
| isolated margin, margin health zones | `aftermath_runtime/safety.py` | `test_safety.py` |
| two-tier circuit breakers | `aftermath_runtime/safety.py` | `test_safety.py` |
| heartbeat kill switch with **verified** cancellation | `aftermath_runtime/safety.py` | `test_safety.py` |
| SIGINT/SIGTERM cancel-all, non-zero exit | `aftermath_runtime/safety.py` | `test_safety.py` |
| serialised deposits | `aftermath_runtime/safety.py` | `test_safety.py` |
| ID discipline (§1) | `aftermath_runtime/ids.py` | `test_ids.py` |
| sign the digest, never the bytes (§2) | `aftermath_runtime/ptb.py` | `test_ptb.py` |
| previews are a tagged union (§6) | `aftermath_runtime/ptb.py` | `test_ptb.py` |
| BigInt `"...n"` wire format (§11) | `aftermath_runtime/ids.py`, `execution.py` | `test_ids.py`, `test_execution.py` |
| `deferShare` returns deferred refs (§12) | `aftermath_runtime/ptb.py` | `test_ptb.py` |
| no server-side dead-man switch (§13) | `aftermath_runtime/safety.py` | `test_safety.py` |
| `signatures[]` is plural (§14) | `aftermath_runtime/ptb.py` | `test_ptb.py` |
| refresh state after every mutation | `aftermath_runtime/adapter.py` | `test_adapter.py` |
