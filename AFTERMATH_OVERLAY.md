# Aftermath strategy overlay

This branch is pinned to Senpi upstream `c3ef08a670581cd20a9d80df17d36f13266605ae`.
It ports strategy content onto a separate, Aftermath-native venue boundary
instead of emulating Hyperliquid/Senpi MCP response shapes.

The first canary is Rooster. Its pure scoring and session behavior are
unchanged; its scanner now consumes:

| Rooster input | Aftermath V2 source |
|---|---|
| Available sizing collateral | `/api/perpetuals/accounts/positions` → `accounts[].availableCollateralUsd` |
| Held positions | `accounts[].positions[].marketId/baseAssetAmount` |
| 15m/4h candles | `/api/perpetuals/market/candle-history` → `candles[]` |
| Market identity/capability | live `/api/perpetuals/markets` → `marketDatas[]` |

The scanner emits shadow signals only. `AftermathVenue` has no write method;
`submit_order_intent` and non-read transport paths always raise `WriteDenied`.
See [runtime gates](docs/aftermath-overlay/RUNTIME_GATES.md) before interpreting
this as an executable trading system.

Run the overlay and upstream Rooster tests:

```bash
python3 -m unittest discover -s tests/aftermath_runtime -p 'test_*.py' -v
python3 strategies/rooster/tests/test_engine.py
```
