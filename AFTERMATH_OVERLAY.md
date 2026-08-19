# Aftermath strategy overlay

This branch is pinned to Senpi upstream `c3ef08a670581cd20a9d80df17d36f13266605ae`
and runs the strategy corpus on **Aftermath Perpetuals V2** through one adapter,
rather than porting 99 packages individually. Hyperliquid is removed from the
execution path — not proxied underneath it.

Aftermath API semantics are pinned separately to
`AftermathFinance/skills@5b614db62dcd2e58f442e93661f608fe7b073c32`
(`aftermath-perpetuals` v3.0.0) and the production OpenAPI digest. See
`contracts/aftermath-skills-v3-contract.json`, `aftermath-overlay/provenance.json`
and `AFTERMATH_SKILLS_REF/PINNED.md`. Mutable branch heads are not a build input.

Quickstart and environment variables: see the
[README](README.md#aftermath-v2-runtime--quickstart).

---

## The shape of it

```
strategies/**/scan.py          unmodified, byte-for-byte pinned upstream
        |
        |  ctx.senpi_mcp.call_tool(name, args)      <- the only seam
        v
aftermath_runtime/adapter.py   ONE adapter: the upstream MCP surface,
        |                      served entirely from Aftermath V2
        +-- markets.py         all-markets -> resolved marketIds
        +-- accounts.py        accounts/owned -> auto discovery
        +-- execution.py       atomic primitives (build only)
        +-- ptb.py             build -> preview -> INSPECT -> reconcile
        +-- gas.py             sponsored | self | dynamic
        +-- safety.py          breakers, kill switch, sizing, serialisation
        +-- ids.py             the three account identifiers, kept distinct
        +-- transport.py       injected; no submit route in any allowlist
        +-- harness.py         runs an upstream scan.py against the adapter
```

`aftermath_runtime/mock.py` is an interface-identical twin: zero network, zero
keys. Parity is enforced by a test, not by discipline.

## What is verified, and by what

| claim | test |
|---|---|
| All 99 packages / 125 scanner instances run through the adapter | `test_strategy_runnability.py` — runs every `scan.py` against both adapters |
| No strategy file talks to the API directly | `test_strategy_runnability.py` — greps `strategies/**` |
| Mock and real adapters expose the same surface | `test_adapter.py::InterfaceParityTests` |
| The inspection gate cannot be bypassed | `test_ptb.py::InspectionGateTests` |
| Previews are parsed as a tagged union, failing closed | `test_ptb.py::PreviewUnionTests` |
| The three account identifiers cannot be swapped | `test_ids_and_gas.py::IdTypingTests` |
| BigInt `"...n"` on exactly the documented fields | `test_ptb.py::WireEncodingTests` |
| Circuit breakers latch; the kill switch **verifies** cancellation | `test_safety.py` |
| Gas: three modes, explicit budget, never a silent fallback | `test_ids_and_gas.py::GasModeTests` |
| The retired v1 host appears nowhere outside the vendored skills | `test_host_discipline.py` |
| No upstream venue survives in an execution path | `test_host_discipline.py::VenueRemovalTests` |
| Vendored skills are byte-identical to the pinned commit | `test_vendored_skills.py` |
| `doctor` exits non-zero on a missing wallet | `test_doctor.py` + the CI workflow |

Companion documents:

- [`docs/aftermath-overlay/MCP_TOOL_COVERAGE.md`](docs/aftermath-overlay/MCP_TOOL_COVERAGE.md)
  — every tool, its status, and what backs it.
- [`docs/aftermath-overlay/ATOMICITY.md`](docs/aftermath-overlay/ATOMICITY.md)
  — which multi-step operations are one transaction, which are not, and why.
- [`docs/aftermath-overlay/RUNTIME_GATES.md`](docs/aftermath-overlay/RUNTIME_GATES.md)
  — the read-only gates, before reading this as an executable trading system.
- [`AFTERMATH_SKILLS_REF/README-DELTA.md`](AFTERMATH_SKILLS_REF/README-DELTA.md)
  — the retired-host discrepancy in the vendored skills and in the spec itself.

## The Rooster shadow canary (still here, unchanged)

A separate Rooster shadow port lives under `aftermath-overlay/shadow/harness/`.
It deliberately avoids a nested `strategies/` path so upstream discovery cannot
mistake it for a deployable package. It predates the adapter and consumes the
read-only `AftermathVenue` directly:

| Rooster input | Aftermath V2 source |
|---|---|
| Available sizing collateral | `/api/perpetuals/accounts/positions` → `accounts[].availableCollateralUsd` |
| Held positions | `accounts[].positions[].marketId/baseAssetAmount` |
| 15m/4h candles | `/api/perpetuals/market/candle-history` → `candles[]` |
| Market identity/capability | live `/api/perpetuals/markets` → `marketDatas[]` |

It emits shadow signals only and is not in the enabled or runnable catalog.

## Safety posture

- **Every strategy ships disabled.** The generated catalog still reports 0 enabled.
- **Nothing is signed, submitted, or broadcast.** No submit route appears in any
  transport allowlist, `ptb.submit()` raises, and `sign_inspected()` refuses
  unless armed — and no signer exists to arm.
- **No key is read.** The one required secret is a wallet ADDRESS.
- `AftermathVenue` is unchanged and still denies writes structurally:
  `submit_order_intent` and non-read transport paths always raise `WriteDenied`.

## Running everything

```bash
python3 ci/run_offline_tests.py                 # 244 tests, network denied
python3 tools/generate_coverage.py --check
python3 tools/sync_upstream.py --check
python3 tools/lint_overlay.py
python3 tools/validate_skills_contract.py
python3 -m aftermath_runtime doctor
python3 strategies/rooster/tests/test_engine.py
python3 senpi-strategy-author/scripts/validate_strategy.py strategies/rooster
```
