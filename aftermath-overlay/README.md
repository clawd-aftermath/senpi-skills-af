# Aftermath downstream overlay

This directory turns the upstream Senpi strategy corpus into a deterministic
coverage inventory for an Aftermath-native runtime. It does not impersonate the
proprietary Senpi runtime and it does not make any strategy runnable yet.

The read-only venue boundary and Rooster canary under `shadow/` are test
harnesses, not catalog promotion. Rooster remains `needs-field-mapping`, with
zero enabled strategies, until durable account resolution and every execution
gate are implemented and independently validated.

Canonical relaunch references:

- Site: <https://v2-preview.aftermath.finance>
- Swagger: <https://v2-preview.aftermath.finance/docs>
- OpenAPI: <https://v2-preview.aftermath.finance/api/openapi/spec.json>
- REST prefix: <https://v2-preview.aftermath.finance/api/>
- Skills branch: <https://github.com/AftermathFinance/skills/tree/feat/v2-skills>

Integration semantics derive from the preview OpenAPI plus
`aftermath-perpetuals` skill v3.0.0 at immutable commit
`5b614db62dcd2e58f442e93661f608fe7b073c32`. `AFTERMATH_SKILLS_REF`,
`provenance.json`, and `contracts/aftermath-skills-v3-contract.json` pin the
commit, branch, version, six controlling source files/digests, and extracted
contract. The V2-preview URLs remain the canonical post-relaunch environment.
Offline CI checks manifest consistency. Source-byte authenticity is checked
separately against an already-fetched skills checkout; neither path fetches.
Generation and validation are standard-library-only:

```bash
python3 tools/generate_coverage.py
python3 tools/validate_skills_contract.py
python3 ci/run_offline_tests.py
python3 tools/lint_overlay.py
```

To recompute all six source digests from the pinned git object and prove that
the commit belongs to the fetched branch history:

```bash
python3 tools/validate_skills_contract.py --source-dir /path/to/aftermath-skills
```

The branch may advance; the validator requires the immutable pin to remain an
ancestor, not equal the mutable branch head.

To review a new upstream release, update `UPSTREAM_REF` in a branch, rebase the
repository onto that exact upstream commit, then run the offline sync:

```bash
python3 tools/sync_upstream.py --ref <full-already-fetched-sha>
```

Review the complete inventory and coverage diff. The sync command never
fetches, and it refuses a tree whose `strategies/` differs from the pin. Never
copy a generated catalog forward.
