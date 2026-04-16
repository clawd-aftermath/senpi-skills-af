---
name: fee-optimizer
description: >-
  When to use ALO (fee-optimized) vs MARKET orders on Aftermath Finance via Senpi,
  and standard order params for entry/exit/TP. Use when configuring execution.
license: MIT
compatibility: >-
  Requires Senpi MCP (create_position, close_position, edit_position).
  Aftermath perp only.
metadata:
  author: senpi
  version: "1.1"
  platform: senpi
  exchange: aftermath
---

# Fee Optimizer

Use this skill when the user or another skill needs: (1) fee-aware execution on Aftermath Perpetuals, (2) correct native order type selection, or (3) gas-aware decisions for entries/exits and order refreshes.

## Aftermath Execution Modes (Native)

Aftermath uses numeric `orderType` values on native transactions:

- `orderType: 0` — **GTC** (Good Till Cancelled): standard limit order that can rest on book. If filled passively, pays maker fee.
- `orderType: 2` — **PostOnly**: maker-only order. Rejected if it would cross the spread. This is the primary mode for fee optimization.
- `orderType: 3` — **IOC** (Immediate or Cancel): fills immediately (full or partial) at taker fee; unfilled remainder is canceled.
- `orderType: 1` — **FOK** (Fill or Kill): must fill completely immediately or fail.
- `orderType: "MARKET"` via MCP abstraction: immediate taker execution.

Critical mapping warning:

- **PostOnly is `2`, not `1`.**
- Using `1` while intending PostOnly submits FOK and can produce unexpected behavior, including `MoveAbort 3005` in PostOnly-style flows.

## MCP Mapping (What Agents Usually Pass)

Senpi MCP may expose higher-level order types. Map them to native Aftermath behavior:

- `MARKET` -> immediate taker path.
- `FEE_OPTIMIZED_LIMIT` -> maker-seeking path implemented with native limit/PostOnly logic depending on endpoint/tool behavior.

When fee optimization is the goal, prefer native semantics that guarantee maker intent (`orderType: 2`) and verify execution outcomes.

## Gas Cost Awareness (Sui)

On Sui, every transaction pays gas. Typical range:

- ~`0.001-0.005 SUI` per transaction (roughly `$0.003-$0.02`, market-dependent).

Implications:

- Gas is additive to trading fees.
- On small notionals (often `< $100`), gas can exceed maker-vs-taker fee savings.
- Batch related actions when possible.
- For refresh workflows, prefer native atomic cancel+replace:
  - `POST /api/perpetuals/account/transactions/cancel-and-place-orders`
  - **~7x gas savings** when batching 5+ orders vs separate cancel + place transactions
  - Single order: ~0.002 SUI for cancel + 5 orders vs ~0.004 SUI for cancel + 1 order separately
- **Gas pool sponsorship**: pre-fund a GasPool, include `sponsor` field in requests. Agent wallet never needs SUI.
- **USDC as gas**: deposit USDC into GasPool — auto-swaps to SUI via Aftermath router.

## Fee Breakeven Calculator

Use this per transaction decision rule:

```text
minProfitableSize = gasCost / (takerFee - makerFee)
```

Where:

- `gasCost` is USD-equivalent gas for the transaction.
- `takerFee` and `makerFee` are market-specific fee rates for the target market/tier.

Interpretation:

- If target notional `< minProfitableSize`, fee optimization may not justify extra transaction overhead.
- For very small sizes, prefer single-hop immediate execution (`MARKET` / `IOC`) over extra maker-management transactions.

## Order Selection Guidelines

- Use **PostOnly (`2`)** for planned entries/exits where maker fee capture matters and fill urgency is low.
- Use **GTC (`0`)** when you want a resting limit but can accept eventual taker-like behavior if priced aggressively.
- Use **IOC (`3`)** when immediate partial fill is acceptable and speed matters.
- Use **FOK (`1`)** when partial fills are unacceptable.
- Use **MARKET** for stops, emergency exits, and strictly time-sensitive execution.

**References:**
- [references/alo-guide.md](references/alo-guide.md) — Aftermath fee optimization playbook (PostOnly/IOC/GTC/FOK, gas-aware decisions, timing risk).
- [references/order-params.md](references/order-params.md) — MCP-facing order parameter templates by context.

**Scripts:**
- `scripts/get_order_spec.py` — Returns order spec (orderType + options) for a given context (entry, exit_tp, exit_sl, exit_emergency).

## Native Endpoint Notes

For native order refreshes and grid placement:

- `cancel-and-place-orders` returns **`TxKindResponse`** (`txKind` base64), not `TransactionBuildResponse`.
- Side encoding is numeric: `0` = bid/long, `1` = ask/short.
- Native prices/sizes use BigInt-string format with trailing `n` (example: `"95000000000n"`).
- For ladder entries, use `place-scale-order` to place a full grid in one transaction and tune distribution with `sizeSkew`.

When you change this skill, bump `metadata.version` in this file so the skill-update checker can notify users; they apply updates with `npx skills update`.
