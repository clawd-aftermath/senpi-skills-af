---
name: gator-strategy
description: >-
  GATOR — Patient funding arbitrage. Enters against extreme funding (120%+ annualized) to
  collect payments and position for the mean-reversion snap. No time-based exits — structural
  thesis invalidation only (funding flips, funding normalizes below 50% ann, OI collapses).
  Tracks accumulated funding income per position. DSL High Water Mode (mandatory).
  The alligator: lies motionless for hours, then snaps.
license: MIT
metadata:
  author: jason-goldberg
  version: "1.0"
  platform: senpi
  exchange: aftermath
---

# GATOR — Patient Funding Arbitrage

Lies motionless for hours. Collects funding. Then snaps.

Evolved from CROC's live trading failure: CROC lost 14% because momentum DSL rules (15-min weak peak, 30-min hard timeout) killed funding arb trades that need hours to play out. GATOR removes all time-based exits and uses structural thesis invalidation instead.

## What Makes GATOR Different from CROC

CROC uses the same DSL rules as momentum strategies. GATOR uses funding-specific exit logic:

| Aspect | CROC | GATOR |
|---|---|---|
| Min funding | 20% annualized | **120% annualized** — absolute extremes only |
| Weak peak cut | 15 min (or widened by agent) | **Disabled** |
| Hard timeout | 30 min (or widened by agent) | **Disabled** |
| Primary exit | Time-based (DSL Phase 1 timeout) | **Structural (funding flips = exit)** |
| Funding flip exit | Not implemented | **Instant — funding reverses direction = thesis dead** |
| Funding normalize exit | Not implemented | **Funding drops below 50% ann = arb is over** |
| OI collapse exit | Not implemented | **OI drops 20%+ in 2h = chaotic unwind, take what you have** |
| Funding income tracking | None | **Tracks income per position** |
| Phase 2 trigger | +7% ROE | **+10% ROE** — funding arb is slower |
| Stagnation TP | 30 min | **180 min** — funding trades are slow by design |

## MANDATORY: DSL High Water Mode

**GATOR MUST use DSL High Water Mode. This is not optional.**

Spec: https://github.com/Senpi-ai/senpi-skills/blob/main/dsl-dynamic-stop-loss/dsl-high-water-spec%201.0.md

When creating DSL state files, you MUST include:

```json
{
  "lockMode": "pct_of_high_water",
  "phase2TriggerRoe": 10,
  "tiers": [
    {"triggerPct": 10, "lockHwPct": 20, "consecutiveBreachesRequired": 3},
    {"triggerPct": 20, "lockHwPct": 40, "consecutiveBreachesRequired": 3},
    {"triggerPct": 35, "lockHwPct": 60, "consecutiveBreachesRequired": 2},
    {"triggerPct": 50, "lockHwPct": 75, "consecutiveBreachesRequired": 1},
    {"triggerPct": 75, "lockHwPct": 85, "consecutiveBreachesRequired": 1}
  ]
}
```

**FALLBACK:** Use `tiersLegacyFallback` from config until engine supports `pct_of_high_water`.

**CRITICAL: Do NOT use momentum DSL rules on GATOR. No hard timeouts, no weak peak cuts, no dead weight. These will kill funding trades that are working exactly as designed — collecting funding while consolidating sideways.**

## Aftermath Funding Rate Integration

**CRITICAL:** Do NOT use `estimatedFundingRate` from ticker/market endpoints. On Aftermath it is 12.5x inflated.

Use `/api/perpetuals/all-markets` and compute:

```ts
const ratePerPeriod = market.marketState.premiumTwap / market.indexPrice; // per 8h
const annualizedPct = Math.abs(ratePerPeriod) * 3 * 365 * 100;
const dailyFundingIncomeUsd = Math.abs(ratePerPeriod) * positionSizeUsd * 3;
```

- Entry gate: `120%` annualized means `abs(premiumTwap / indexPrice) >= 0.00110` per 8h period
- Funding-normalized exit: below `50%` annualized means `abs(premiumTwap / indexPrice) < 0.000457` per 8h period
- Funding flip exit and direction checks must use the sign of `premiumTwap` / `ratePerPeriod`

## How GATOR Trades

### Entry (score ≥ 6)

Every 15 minutes, scan all assets for extreme funding:

| Signal | Points |
|---|---|
| Funding ≥ 200% annualized | 4 |
| Funding ≥ 150% annualized | 3 |
| Funding ≥ 120% annualized | 2 |
| Deep OI (> $20M) | 2 |
| Moderate OI (> $10M) | 1 |
| SM aligned with entry direction | 1 |
| Trend confirms entry direction | 1 |

Direction: OPPOSITE to funding. Positive funding (crowd long) = enter short. Negative funding (crowd short) = enter long.

Conviction-scaled margin: 200%+ ann = 30% of account, 150%+ = 25%, 120%+ = 20%.

### Hold

The scanner re-validates every held position on each scan. The position holds as long as:
- Funding has NOT flipped direction
- Funding is still above 50% annualized
- OI has not collapsed 20%+ in 2 hours

A funding trade can hold for 2 hours, 8 hours, 24 hours — as long as the thesis is alive. Every hour it holds, it collects funding payments at 120%+ annualized rates. The longer it holds, the more income subsidizes the position's risk.

### Exit Triggers (any one = close immediately)

| Trigger | What It Means |
|---|---|
| **Funding flips direction** | The crowd unwound. Thesis is dead. |
| **Funding drops below 50% ann** | The extreme normalized. The arb is over. |
| **OI collapses 20%+ in 2h** | Chaotic unwind. Take what you have. |
| **DSL breach** | High Water stop hit — mechanical exit. |

No time exits. No "it's been 30 minutes and nothing happened." Funding arb IS "nothing happening" — you're collecting payments while price consolidates.

## DSL: Widest Tiers in the Zoo

Funding arb entries retrace hard before the snap. The crowd doesn't give up easily — price pushes against you before it reverses. GATOR needs the widest Phase 1 and the most patient Phase 2:

| Setting | Value | Compare to FOX |
|---|---|---|
| Floor base | 3.5% notional | FOX: 1.5% |
| Phase 2 trigger | +10% ROE | FOX: +7% |
| T1 lock | 20% of HW | FOX: 40% |
| 85% trail at | +75% ROE | FOX: +20% |
| Stagnation TP | 15% ROE, 180 min | FOX: 10%, 45 min |

## Risk Management

| Rule | Value |
|---|---|
| Max positions | 3 |
| Max entries/day | 4 (base 3, dynamic to 5) |
| Daily loss limit | 8% |
| Max drawdown | 20% |
| Max single loss | 10% |
| Cooldown | 120 min after 2 consecutive losses |

## Cron Architecture

| Cron | Interval | Session | Purpose |
|---|---|---|---|
| Scanner | 15 min | isolated | Funding scan + thesis validation for held positions |
| DSL v5 | 3 min | isolated | High Water Mode trailing (safety net) |

**15-minute scanner interval is intentional.** Funding rates change hourly. Scanning every 3 minutes wastes tokens on data that hasn't moved. The DSL cron still runs every 3 minutes for mechanical trailing protection.

## Notification Policy

**ONLY alert:** Position OPENED (asset, direction, funding rate, annualized %), position CLOSED (which thesis exit triggered or DSL breach), risk triggered, critical error.
**NEVER alert:** Scanner found nothing, DSL routine, thesis validation passed, funding income update, any reasoning.
All crons isolated. `NO_REPLY` for idle cycles.

## Bootstrap Gate

Check `config/bootstrap-complete.json` every session. If missing:
1. Verify Senpi MCP
2. Create scanner cron (15 min, isolated) and DSL cron (3 min, isolated)
3. Write `config/bootstrap-complete.json`
4. Send: "🐊 GATOR is online. Scanning for 120%+ annualized funding. Structural exits only. Silence = no extremes."

## Expected Behavior

| Metric | CROC | GATOR (expected) |
|---|---|---|
| Trades/day | 5-10 | **2-4** |
| Avg hold time | 15-30 min (killed by timeout) | **2-8 hours** |
| Win rate | ~35-40% | **~55-65%** |
| Avg winner | 10-20% ROE | **15-40%+ ROE** |
| Avg loser | -3 to -8% ROE (many small) | **-15 to -25% ROE** (fewer, bigger) |
| Funding income/trade | Minimal (15 min holds) | **Significant (hours at 120%+ ann)** |
| Fee drag/day | $30-50 | **$5-15** |

## Files

| File | Purpose |
|---|---|
| `scripts/gator-scanner.py` | Funding scan + thesis validation + funding income tracking |
| `scripts/gator_config.py` | Shared config, MCP helpers |
| `config/gator-config.json` | All variables with thesis exit config + DSL High Water |

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
