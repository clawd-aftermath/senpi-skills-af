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
- Skills: <https://github.com/AftermathFinance/skills>

The exact upstream SHA and OpenAPI digest are pinned in `UPSTREAM_REF` and
`provenance.json`. Generation is standard-library-only and offline:

```bash
python3 tools/generate_coverage.py
python3 ci/run_offline_tests.py
python3 tools/lint_overlay.py
```

To review a new upstream release, update `UPSTREAM_REF` in a branch, rebase the
repository onto that exact upstream commit, then run the offline sync:

```bash
python3 tools/sync_upstream.py --ref <full-already-fetched-sha>
```

Review the complete inventory and coverage diff. The sync command never
fetches, and it refuses a tree whose `strategies/` differs from the pin. Never
copy a generated catalog forward.
