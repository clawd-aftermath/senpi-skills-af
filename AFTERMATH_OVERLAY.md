# Aftermath strategy overlay

This branch is pinned to Senpi upstream `c3ef08a670581cd20a9d80df17d36f13266605ae`.
It ports strategy content onto a separate, Aftermath-native venue boundary
instead of emulating Hyperliquid/Senpi MCP response shapes.

The first canary is a separate Rooster shadow port under
`aftermath-overlay/shadow/harness/`. It deliberately avoids a nested
`strategies/` path so upstream discovery cannot mistake it for a deployable
package. Upstream strategy sources remain byte-for-byte
pinned. The port keeps Rooster's pure scoring and session behavior unchanged
while consuming:

| Rooster input | Aftermath V2 source |
|---|---|
| Available sizing collateral | `/api/perpetuals/accounts/positions` → `accounts[].availableCollateralUsd` |
| Held positions | `accounts[].positions[].marketId/baseAssetAmount` |
| 15m/4h candles | `/api/perpetuals/market/candle-history` → `candles[]` |
| Market identity/capability | live `/api/perpetuals/markets` → `marketDatas[]` |

The scanner emits shadow signals only. It is not listed in the enabled or
runnable catalog: coverage still classifies upstream Rooster as
`needs-field-mapping` because durable wallet/account resolution and the
execution supervisor do not exist. `AftermathVenue` has no write method;
`submit_order_intent` and non-read transport paths always raise `WriteDenied`.
See [runtime gates](docs/aftermath-overlay/RUNTIME_GATES.md) before interpreting
this as an executable trading system.

Run all downstream tests with process-wide network denial, then the upstream
Rooster tests:

```bash
python3 ci/run_offline_tests.py
python3 strategies/rooster/tests/test_engine.py
```
