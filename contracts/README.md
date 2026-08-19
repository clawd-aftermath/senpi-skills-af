# Aftermath V2 read contract

`selected-openapi-contract.json` is generated from the canonical V2 OpenAPI
document, not edited by hand.

```bash
python3 tools/generate_openapi_contract.py \
  /path/to/spec.json \
  contracts/selected-openapi-contract.json
```

Local regeneration validation uses the same command with `--check` and a
separately supplied canonical source document; it exits nonzero if the pin,
selected paths, referenced schemas, or generated file drift. CI does not fetch
or vendor the full OpenAPI document. It validates the committed selected
contract, source digest, required paths, and known blocking drift through the
offline contract tests.

The generator hashes canonical JSON, so whitespace and object-key order do not
change the pin. The pinned canonical SHA-256 is
`fbc76c20bb3581a638d59ff5afc2c1dfd2f47d7453f14327aab8a8e5d34ca9f4`.

Integration semantics are independently pinned to the
`AftermathFinance/skills` `feat/v2-skills` branch at immutable commit
`5b614db62dcd2e58f442e93661f608fe7b073c32`, skill v3.0.0. The extracted,
network-free contract is `aftermath-skills-v3-contract.json`. It enumerates all
15 blobs under `skills/api`: seven applied documents (including `ccxt.md`) and
eight explicitly out-of-scope blobs with reasons. Digests and classifications
are duplicated in `provenance.json`. The repository top-level directory set and
all `skills/*` directories are also pinned; `skills/gas` is explicitly out of
scope. These records are checked by:

```bash
python3 tools/validate_skills_contract.py
```

That offline check proves internal manifest consistency. Immediately fetch the
official remote ref, then authenticate the recorded hashes and complete tree
against git objects:

```bash
git -C /path/to/aftermath-skills fetch origin feat/v2-skills
python3 tools/validate_skills_contract.py \
  --source-dir /path/to/aftermath-skills
```

The source check hashes raw file bytes stored at the pinned commit and requires
that commit to be an ancestor of the fetched branch ref. It does not fetch and
does not require the mutable branch head to remain equal to the pin. A stale
local remote ref can conceal a force-push that orphaned the commit; freshness is
the operator's responsibility and the verifier reports the exact observed tip.

The production OpenAPI is authoritative for endpoint schemas. The pinned
skills define integration semantics and safety behavior. Wire contradictions
are recorded in `known-drift.json`: positions request items and documented
native BigInt response fields use integer schemas while their descriptions
require trailing-`n` strings, and the candle request's containing description
still names the removed pre-v3 field even though its property/required list
uses `resolution`. The overlay follows the explicit field descriptions and the
pinned v3 skill for shadow reads, never guesses. Unexpected BigInt response
shapes raise a machine-readable `ContractDriftError`. The BigInt mismatches
remain blocking for live promotion pending schema correction or authenticated
non-production validation; the stale candle prose is resolved by the actual
required property and pinned skill.

Known contract drift: the pinned schema describes
`POST /api/perpetuals/markets` as returning `orderbooks`, while production
returns `marketDatas` containing the market metadata needed for safe tick, lot,
funding-interval, and symbol normalization. `MarketRegistry` deliberately
requires `marketDatas`; it will not guess units from the orderbook-only schema.
This gate must be resolved before a production release. The blocking divergence
is also recorded in `known-drift.json` so a passing SHA check cannot be
misread as API/code agreement.
