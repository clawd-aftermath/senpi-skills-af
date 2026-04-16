# Senpi Fee Optimization (Aftermath Perpetuals)

This guide explains when to use Aftermath maker-style execution vs taker-style execution in Senpi, with gas-aware decision rules.

## 1) Fee Structure Reality on Aftermath

- Aftermath fees are **market-dependent** (not one flat schedule across all instruments).
- Maker and taker tiers can differ by market and account tier.
- `gasPriceTakerFee` in market params is relevant for gas-price style taker flows.
- Senpi/platform fees may still apply on top of venue fees.

Always calculate using live fee inputs for the exact market.

## 2) Native Order Types (Critical Mapping)

Aftermath native `orderType` values:

- `0` = GTC (Good Till Cancelled)
- `1` = FOK (Fill or Kill)
- `2` = PostOnly (maker-only)
- `3` = IOC (Immediate or Cancel)

Important gotcha:

- **Type `1` is FOK, not PostOnly.**
- **PostOnly is type `2`.**
- Mixing this up can trigger `MoveAbort 3005` when the order path expects PostOnly behavior.

## 3) Maker Optimization Path

For fee optimization on Aftermath, the canonical maker path is:

- Use **PostOnly (`orderType: 2`)** to guarantee maker-only intent.
- If the price would cross the spread, order is rejected (no taker fallback at native level).

PostOnly trade-off:

- Better fees when filled.
- Higher risk of rejection and slower fill than immediate taker execution.

## 4) Gas Must Be Included in Fee Math

On Sui, every transaction costs gas (typically ~`0.001-0.005 SUI`).

This means:

- Round-trip cost is not just maker/taker fees.
- For smaller notionals, gas can dominate total execution cost.
- More tx count (place, cancel, replace) can erase fee edge from maker fills.

### Breakeven Notional

Use per-tx breakeven:

```text
minProfitableSize = gasCost / (takerFee - makerFee)
```

- `gasCost`: USD-equivalent gas for the additional maker-management transaction(s).
- `takerFee - makerFee`: fee delta for the target market.

If intended size is below this threshold, prefer a single immediate route (`IOC` / `MARKET`) over extra maker attempts.

## 5) PostOnly vs IOC vs GTC

Use **PostOnly (`2`)** when:

- Fee minimization is the main objective.
- Fill urgency is low/moderate.
- You can tolerate occasional rejects and retries.

Use **IOC (`3`)** when:

- You need immediate execution.
- Partial fills are acceptable.
- You accept taker fees to reduce timing risk.

Use **GTC (`0`)** when:

- You want a resting limit without strict maker-only rejection behavior.
- You plan to manage lifecycle (monitor, cancel, reprice) explicitly.

Use **FOK (`1`)** when:

- You require all-or-nothing immediate fill.
- Partial fills are operationally harmful.

Use **`MARKET`** (MCP abstraction) when:

- Stop loss / emergency exit / liquidation-risk reduction needs speed over fees.

## 6) PostOnly Rejection Risk (MoveAbort 3005)

Tight spreads and stale book snapshots can cause PostOnly requests to cross inadvertently and fail with `MoveAbort 3005`.

Mitigations:

- Refresh top-of-book before submitting/retrying.
- Place with a conservative non-crossing cushion.
- Retry with updated price only if still fee-positive after extra gas.

## 7) Gas-Saving Execution Patterns

### Programmable Transaction Blocks (PTBs)

Sui's PTBs let you compose multiple operations into a **single atomic transaction**. This is the foundation of gas efficiency on Aftermath:

- **Cancel old orders and place new orders in one tx** — no gap where you have no orders on the book
- **Update quotes across multiple price levels atomically** — your entire grid refreshes at once
- **Pay gas only once** for what would be 10+ transactions on other chains
- **All-or-nothing execution** — no partial state if something fails

### Atomic Cancel-and-Place

For refresh/update flows, use atomic cancel+replace:

- Endpoint: `POST /api/perpetuals/account/transactions/cancel-and-place-orders`
- **~7x gas savings** when batching 5+ orders vs separate cancel + place transactions
- Return type: `TxKindResponse` (`txKind` base64), not `TransactionBuildResponse`

```
Inefficient (separate):
  cancel_orders       → ~0.0016 SUI
  place_limit_order   → ~0.0023 SUI
  Total: ~0.004 SUI for 1 order update

Efficient (atomic + batched):
  cancel + place ×5   → ~0.002 SUI total
  Gas per order: ~0.0004 SUI
```

Native payload details:

- Side encoding is numeric (`0` bid/long, `1` ask/short).
- Prices/sizes use BigInt strings with trailing `n` (example: `"95000000000n"`).
- `sponsor` field (optional) for gas pool sponsorship.

### Gas Pool Sponsorship

Pre-fund a GasPool so agent wallets never need SUI:

- Create: `POST /api/gas-pool/transactions/create`
- Deposit (SUI or USDC): `POST /api/gas-pool/transactions/deposit` — USDC auto-swaps to SUI via Aftermath router
- Grant agent: `POST /api/gas-pool/transactions/grant`
- Trade with `sponsor.walletAddress` in requests — API returns `txKind` + `sponsorSignature`

See [docs/aftermath/gasless-trading.md](../../docs/aftermath/gasless-trading.md) for full setup.

### Sui Storage Rebates

Cancelling orders returns a portion of the gas paid when placing them. For skills that continuously refresh quotes, this rebate significantly reduces the effective cost of quoting.

### Scale Orders for Ladder/Grid Entries

For ladders/grids:

- Endpoint: `POST /api/perpetuals/account/transactions/place-scale-order`
- Places multiple limits in one transaction across a range.
- `sizeSkew=1.0` gives uniform sizing; higher values overweight later levels.

## 8) Real-World Timing Considerations

- PostOnly generally fills slower than immediate taker routes.
- In volatile conditions, waiting for maker fill can cost more in slippage/opportunity than fee savings.
- Sequential multi-leg PostOnly entries create timing exposure (leg A fills, leg B waits, hedge drifts).

Practical rule:

- Fee-first for non-urgent, single-leg placement.
- Speed-first (`IOC`/`MARKET`) for time-coupled legs, stop logic, and risk-off flows.
