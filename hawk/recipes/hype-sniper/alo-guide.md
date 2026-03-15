# Senpi Fee Optimization (ALO) — Guide for Trading Agents

## Fee Comparison

| | Taker (MARKET) | Maker (ALO) |
|---|---|---|
| Aftermath fee (varies by market) | Market-dependent taker fee | Market-dependent maker fee |
| Senpi builder fee | 5 bps | 5 bps |
| **Round-trip cost** | **Higher fee impact** | **Lower fee impact** |

## How To Use

### 1. Aggressive (MARKET) — immediate fill, highest fees
```
orderType: "MARKET"
```

### 2. Fee-optimized with guaranteed fill (recommended for entries)
```
orderType: "FEE_OPTIMIZED_LIMIT"
ensureExecutionAsTaker: true
```
Places maker order, falls back to market after 60s. Blocks for up to 60s.

### 3. Fee-optimized resting (patient)
```
orderType: "FEE_OPTIMIZED_LIMIT"
ensureExecutionAsTaker: false
```
Stays on book until filled or cancelled. Monitor via `strategy_get_open_orders`.

## Constraints
- `limitPrice`, `timeInForce`, `slippagePercent` CANNOT be used with `FEE_OPTIMIZED_LIMIT`
- TP/SL can still be set alongside ALO orders
- `strategy_close` always uses market internally
- `edit_position` also supports `FEE_OPTIMIZED_LIMIT`

## Recommended Hybrid Approach
```
Entries:  FEE_OPTIMIZED_LIMIT + ensureExecutionAsTaker: true
Closes:   MARKET (for stops/emergencies), ALO (for take-profits)
SL/TP:    Always MARKET
```

Typically reduces fee drag on planned entries because maker/taker fees vary by market on Aftermath.

Estimate savings using your strategy's notional and the current market-specific Aftermath maker/taker schedule.

## Detection
Response includes `executionAsMaker: true/false` in `mainOrder` object.
