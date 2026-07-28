# Native Perpetuals Endpoint Reference

> Native perpetuals endpoints under `/api/perpetuals/*`.

This is the preferred and canonical API surface for integrations because it exposes the complete feature set beyond CCXT compatibility.

Verified against OpenAPI: `https://v2-preview.aftermath.finance/api/openapi/spec.json`
Last validated: `2026-07-28`

---

## Endpoint Families

### Accounts and positions

```text
POST /api/perpetuals/accounts/owned
POST /api/perpetuals/accounts
POST /api/perpetuals/accounts/positions
POST /api/perpetuals/account/max-order-size
POST /api/perpetuals/account/order-history
POST /api/perpetuals/account/order-history-detailed
POST /api/perpetuals/account/order-history-detailed-csv
POST /api/perpetuals/account/collateral-history
POST /api/perpetuals/account/margin-history
POST /api/perpetuals/account/stop-order-datas
POST /api/perpetuals/account/twap-order-datas
```

### Account previews and tx builders

```text
POST /api/perpetuals/account/previews/*
POST /api/perpetuals/account/transactions/*
```

Top-used explicit routes:

```text
POST /api/perpetuals/account/previews/place-market-order
POST /api/perpetuals/account/previews/place-limit-order
POST /api/perpetuals/account/previews/place-scale-order
POST /api/perpetuals/account/previews/cancel-orders
POST /api/perpetuals/account/previews/set-leverage
POST /api/perpetuals/account/previews/edit-collateral

POST /api/perpetuals/account/transactions/place-market-order
POST /api/perpetuals/account/transactions/place-limit-order
POST /api/perpetuals/account/transactions/place-scale-order
POST /api/perpetuals/account/transactions/cancel-orders
POST /api/perpetuals/account/transactions/cancel-and-place-orders
POST /api/perpetuals/account/transactions/set-leverage
POST /api/perpetuals/account/transactions/deposit-collateral
POST /api/perpetuals/account/transactions/withdraw-collateral
POST /api/perpetuals/account/transactions/allocate-collateral
POST /api/perpetuals/account/transactions/deallocate-collateral
POST /api/perpetuals/account/transactions/transfer-collateral
POST /api/perpetuals/account/transactions/place-stop-orders
POST /api/perpetuals/account/transactions/place-sl-tp-orders
POST /api/perpetuals/account/transactions/edit-stop-orders
POST /api/perpetuals/account/transactions/cancel-stop-orders
POST /api/perpetuals/account/transactions/create-twap-orders
POST /api/perpetuals/account/transactions/edit-twap-orders
POST /api/perpetuals/account/transactions/cancel-twap-orders
POST /api/perpetuals/account/transactions/share
POST /api/perpetuals/account/transactions/grant-agent-wallet
POST /api/perpetuals/account/transactions/revoke-agent-wallet
```

### Market data

```text
POST /api/perpetuals/all-markets
POST /api/perpetuals/markets
POST /api/perpetuals/markets/prices
POST /api/perpetuals/markets/24hr-stats
POST /api/perpetuals/markets/orderbooks
POST /api/perpetuals/market/candle-history
POST /api/perpetuals/market/funding-history
POST /api/perpetuals/market/order-history
```

### Vaults

```text
POST /api/perpetuals/vaults
POST /api/perpetuals/vaults/lp-coin-prices
POST /api/perpetuals/vaults/owned-lp-coins
POST /api/perpetuals/vaults/owned-vault-caps
POST /api/perpetuals/vaults/owned-vault-assistant-caps
POST /api/perpetuals/vaults/owned-withdraw-requests
POST /api/perpetuals/vaults/withdraw-requests
POST /api/perpetuals/vaults/predeposits/user-total-deposits
POST /api/perpetuals/vaults/predeposits/vault-totals
GET  /api/perpetuals/vaults/{vault_id}/tvl
POST /api/perpetuals/vault/stop-order-datas
POST /api/perpetuals/vault/twap-order-datas
POST /api/perpetuals/vault/previews/*
POST /api/perpetuals/vault/transactions/*
```

### WebSocket proxy

```text
GET /api/perpetuals/ws/updates
```

The relaunch spec no longer exposes the legacy market-candles WebSocket route.
Use `/api/perpetuals/market/candle-history` for snapshots and
`/api/perpetuals/ws/updates` for live updates.

---

## Identifier Rules

| Field | Meaning |
|---|---|
| `accountId` | Numeric account ID |
| `marketId` | Market object ID |
| `vaultId` | Vault object ID |

Do not pass CCXT account capability object IDs (`0x...`) where numeric `accountId` is required.

---

## Relaunch Schema Changes

### Candle history

```http
POST /api/perpetuals/market/candle-history
Content-Type: application/json

{
  "marketId": "0x...",
  "fromTimestamp": 1785258000000,
  "toTimestamp": 1785261600000,
  "resolution": "15m"
}
```

Use a CCXT-style `resolution`; `intervalMs` is not accepted by the relaunch
schema.

### Client-managed order IDs

- Native orders may include `clientOrderId`.
- Cancellation payloads may include `clientOrderIds` in addition to on-chain
  `orderIds`.
- Pending orders return nullable `clientOrderId`.

### Stop-loss and take-profit

Inline SL/TP fields are now `stopLossPrice`, `takeProfitPrice`, and
`triggerPriceType` (`0` index, `1` book mid, `2` mark). The legacy
`stopLossIndexPrice` / `takeProfitIndexPrice` names are not in the relaunch
schema.

### Market response changes

- `/api/perpetuals/markets` accepts omitted or empty `marketIds` to return all
  markets.
- Market params may expose optional, nullable `priorityTakerFee`. Treat an
  absent or null value as "priority-gas acceptance not enabled"; the legacy
  `gasPriceTakerFee`, `gasPriceTwapPeriodMs`, `zScoreThreshold`, and
  `forceCancelFee` fields are gone.
- Price feed IDs are numeric storage IDs in the relaunch schema.
- Position responses no longer expose position-level `makerFee` / `takerFee`.

---

## Preview error semantics

Some preview routes can return HTTP `200` with:

```json
{ "error": "..." }
```

Treat preview responses as success/error unions.

---

## Source of Truth

- Swagger UI: `https://v2-preview.aftermath.finance/docs`
- OpenAPI JSON: `https://v2-preview.aftermath.finance/api/openapi/spec.json`
