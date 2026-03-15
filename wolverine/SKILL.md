---
name: wolverine-strategy
description: >-
  WOLVERINE v1.0 — HYPE alpha hunter with position lifecycle. Single asset, every signal
  (SM, funding, OI, 4TF trend, volume, BTC correlation). Three-mode lifecycle:
  HUNTING (scan for entry) / RIDING (DSL trails) / STALKING (watch for reload on dip).
  After DSL takes profit, watches for fresh momentum impulse while confirming macro thesis
  is intact. If thesis dies, resets. If dip reloads, re-enters. DSL High Water Mode (mandatory).
license: MIT
metadata:
  author: jason-goldberg
  version: "1.1"
  platform: senpi
  exchange: aftermath
  base_skill: grizzly-v2.0
---

# WOLVERINE v1.1 — HYPE Alpha Hunter with Position Lifecycle

One asset. Every signal. Maximum conviction. Reload-on-dip.

## v1.1 Changes — DSL Recalibrated for HYPE Speed

Day 1 data: Wolverine caught a textbook HYPE LONG — score 10+, SM aligned, peaked at +9.3% ROE (+$18.54). Then gave it ALL back because the DSL was too loose. Price dropped from +9.3% to -2.3% ROE faster than the 3-minute scan could react. The old Tier 1 locked only 20% of high water = 1.86% floor, which was meaningless.

**v1.1 fix:** Phase 2 trigger lowered from 6% to 3% ROE. Tier 1 lock raised from 20% to 40%. Breaches reduced from 3 to 2. HYPE reverses fast — the DSL must lock profits aggressively.

With v1.1 DSL, that same trade locks +3.7% ROE at worst instead of exiting at -2.3%.

**Also in v1.1:** BTC correlation is bonus-only, never a gate or thesis exit. HYPE moves independently of BTC — up 50% while BTC dropped 30%. When BTC confirms, HYPE runs harder (+2 score bonus). When BTC diverges, it's a non-event.

WOLVERINE stares at HYPE and nothing else. Every signal source available — smart money positioning, funding rate, open interest, 4-timeframe trend structure, volume, BTC correlation — feeds into a single thesis: is there a high-conviction HYPE trade right now?

Based on GRIZZLY v2.0's three-mode lifecycle, adapted for HYPE's volatility profile.

## The Three-Mode Lifecycle

### MODE 1 — HUNTING (default)

Scan HYPE every 3 minutes. All signals must align (4h trend, 1h momentum, SM, funding, OI, volume). Score 10+ to enter. When a position opens, switch to MODE 2.

### MODE 2 — RIDING

Active position. DSL High Water trails it. Thesis re-evaluation every scan. If thesis breaks (4h trend flips, SM flips, funding extreme, volume dies) -> thesis exit and reset to MODE 1. If DSL closes the position -> switch to MODE 3. Note: BTC divergence does NOT invalidate HYPE thesis — HYPE moves independently.

### MODE 3 — STALKING

DSL locked profits. The trend may not be over. Watch for a reload opportunity. Every scan checks:

**Reload conditions (ALL must pass):**
1. At least one completed 1h candle since exit (~30 min minimum)
2. Fresh 5m momentum impulse in the exit direction
3. OI stable or growing
4. Volume at least 50% of original entry
5. Funding not spiked into crowded territory
6. SM still aligned in the exit direction
7. 4h trend structure still intact

If ALL pass -> RELOAD. Re-enter same direction with dynamic leverage clamp (`lev = min(targetLev, market.maxLeverage())`). Switch to MODE 2.

**Kill conditions (ANY triggers reset to MODE 1):**
- 4h trend reversed
- SM flipped against exit direction
- OI collapsed 20%+
- Stalking for more than 6 hours with no reload
- Funding spiked above 100% annualized

**maxPositions: 1.** WOLVERINE holds one HYPE position at a time.

## MANDATORY: DSL High Water Mode

**WOLVERINE MUST use DSL High Water Mode. This is not optional.**

On Aftermath, initial SL is set inline with the entry order via the `slTp` field. DSL cron handles trailing updates only.

Spec: https://github.com/Senpi-ai/senpi-skills/blob/main/dsl-dynamic-stop-loss/dsl-high-water-spec%201.0.md

DSL tiers in `wolverine-config.json`. Arm DSL immediately after every entry fill. Zero naked positions.

## Why HYPE-Only at 5-10x Leverage

- **Native to Aftermath** — deepest on-exchange liquidity for HYPE
- **Platform momentum** — HYPE price correlates with Aftermath volume/TVL growth
- **High volatility** — moves fast, rewards conviction entries with wide trails
- **BTC as bonus, not filter** — when BTC runs with HYPE, the move is amplified (+2 score bonus). But HYPE often decouples during platform-specific events, so BTC divergence is never a penalty or exit signal
- **Lower leverage compensates for volatility** — 10x on HYPE captures large structural moves without overexposure

## How WOLVERINE Trades

### Entry (score >= 10 required)

Every 3 minutes, the scanner evaluates HYPE across all signal sources:

| Signal | Points | Required? |
|---|---|---|
| 4h trend structure (higher lows / lower highs) | 3 | **Yes** |
| 1h trend agrees with 4h | 2 | **Yes** |
| 15m momentum confirms direction | 0-1 | **Yes** |
| 5m alignment (all 4 timeframes agree) | 1 | No |
| SM aligned with direction | 2-3 | **Hard block if opposing** |
| Funding pays to hold the direction | 2 | No |
| Volume above average | 1-2 | No |
| OI growing | 1 | No |
| BTC confirms move | 2 | No (bonus only — HYPE moves independently of BTC) |
| RSI has room | 1 | No (blocks overbought/oversold) |
| 4h momentum strength | 1 | No |

Maximum score: ~18. Minimum to enter: 10.

### Conviction-Scaled Leverage

| Score | Leverage |
|---|---|
| 10-11 | 8x |
| 12-13 | 9x |
| 14+ | 10x |

Runtime rule (required):

```text
maxLev = market.maxLeverage()
lev = min(targetLev, maxLev)
```

Aftermath is isolated margin per position: pass `collateralChange` on entry and confirm available unallocated collateral with `POST /api/perpetuals/account/max-order-size`.

### Conviction-Scaled Margin

| Score | Margin |
|---|---|
| 10-11 | 20% of account |
| 12-13 | 25% |
| 14+ | 30% |

## Risk Management

| Rule | Value |
|---|---|
| Max positions | 1 |
| Phase 1 floor | 2.5% notional (~25% ROE at 10x) |
| Drawdown halt | 25% from peak |
| Daily loss limit | 10% |
| Cooldown | 120 min after 3 consecutive losses |
| Stagnation TP | 10% ROE stale 75 min |

## Cron Architecture

| Cron | Interval | Session | Purpose |
|---|---|---|---|
| Scanner | 3 min | isolated | Thesis builder + re-evaluator + stalk/reload |
| DSL v5 | 3 min | isolated | High Water Mode trailing stops |

Both MUST be isolated sessions with `agentTurn`. Use `NO_REPLY` for idle cycles.

## Notification Policy

**ONLY alert:** Position OPENED (direction, leverage, score, reasons), position CLOSED (DSL or thesis exit), risk guardian triggered, critical error.
**NEVER alert:** Scanner found no thesis, thesis re-eval passed, DSL routine, any reasoning.

## Bootstrap Gate

On EVERY session, check `config/bootstrap-complete.json`. If missing:
1. Verify Senpi MCP
2. Create scanner cron (3 min, isolated) and DSL cron (3 min, isolated)
3. Write `config/bootstrap-complete.json`
4. Send: "🦡 WOLVERINE is online. Watching HYPE. DSL High Water Mode active. Silence = no conviction."

## Expected Behavior

| Metric | Expected |
|---|---|
| Trades/day | 1-3 |
| Avg hold time | 1-12 hours |
| Win rate | ~45-55% |
| Avg winner | 20-50%+ ROE |
| Avg loser | -20 to -40% ROE |

## Files

| File | Purpose |
|---|---|
| `scripts/wolverine-scanner.py` | HYPE thesis builder + re-evaluator + stalk/reload |
| `scripts/wolverine_config.py` | Shared config, MCP helpers, state I/O |
| `config/wolverine-config.json` | All configurable variables with DSL High Water tiers |

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
