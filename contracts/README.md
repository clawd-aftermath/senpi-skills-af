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
`5bf4f1322ae79561c42bff9329950b757558aea79cce63e89145382024d072f2`.

Integration semantics are independently pinned to the
`AftermathFinance/skills` `feat/v2-skills` branch at immutable commit
`5b614db62dcd2e58f442e93661f608fe7b073c32`, skill v3.0.0. The extracted,
network-free contract is `aftermath-skills-v3-contract.json`; the six
controlling source-file digests are duplicated in `provenance.json` and checked
by:

```bash
python3 tools/validate_skills_contract.py
```

That offline check proves internal manifest consistency. To authenticate the
recorded hashes against git objects in an already-fetched source checkout:

```bash
python3 tools/validate_skills_contract.py \
  --source-dir /path/to/aftermath-skills
```

The source check hashes raw file bytes stored at the pinned commit and requires
that commit to be an ancestor of the fetched branch ref. It does not fetch and
does not require the mutable branch head to remain equal to the pin.

The preview OpenAPI remains authoritative for endpoint schemas. The pinned
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
`POST /api/perpetuals/markets` as returning `orderbooks`, while the live preview
returns `marketDatas` containing the market metadata needed for safe tick, lot,
funding-interval, and symbol normalization. `MarketRegistry` deliberately
requires `marketDatas`; it will not guess units from the orderbook-only schema.
This gate must be resolved before a production release. The blocking divergence
is also recorded in `known-drift.json` so a passing SHA check cannot be
misread as API/code agreement.
