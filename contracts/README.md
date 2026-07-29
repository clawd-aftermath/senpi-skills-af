# Aftermath V2 read contract

`selected-openapi-contract.json` is generated from the canonical V2 OpenAPI
document, not edited by hand.

```bash
python3 tools/generate_openapi_contract.py \
  /path/to/spec.json \
  contracts/selected-openapi-contract.json
```

CI/local validation uses the same command with `--check`; it exits nonzero if
the pin, selected paths, referenced schemas, or generated file drift.

The generator hashes canonical JSON, so whitespace and object-key order do not
change the pin. The pinned canonical SHA-256 is
`5bf4f1322ae79561c42bff9329950b757558aea79cce63e89145382024d072f2`.

Known contract drift: the pinned schema describes
`POST /api/perpetuals/markets` as returning `orderbooks`, while the live preview
returns `marketDatas` containing the market metadata needed for safe tick, lot,
funding-interval, and symbol normalization. `MarketRegistry` deliberately
requires `marketDatas`; it will not guess units from the orderbook-only schema.
This gate must be resolved before a production release. The blocking divergence
is also recorded in `known-drift.json` so a passing SHA check cannot be
misread as API/code agreement.
