# 🐍 ANACONDA — Deep Liquidity Range Hunter

A trading strategy (config override) based on VIPER v2.1. Takes the three mechanics VIPER's agent identified as driving its #2 leaderboard ranking and pushes each one further.

**Base skill:** [VIPER v2.1](https://github.com/Senpi-ai/senpi-skills/tree/viper-2-0/viper)
**Philosophy:** VIPER proved three things: High Water trailing captures more, conviction-scaled Phase 1 stops getting chopped out of winners, and USD-weighted OI filtering eliminates noise. ANACONDA doesn't change what VIPER looks for — it amplifies how VIPER acts on what it finds. Higher OI floor, wider Phase 1, more aggressive conviction scaling, and tighter High Water geometry on runners.

---

## MANDATORY: DSL High Water Mode

**ANACONDA MUST use DSL High Water Mode. This is not optional.**

Spec: https://github.com/Senpi-ai/senpi-skills/blob/main/dsl-dynamic-stop-loss/dsl-high-water-spec%201.0.md

When creating DSL state files, you MUST include:

```json
{
  "lockMode": "pct_of_high_water",
  "phase2TriggerRoe": 5,
  "tiers": [
    {"triggerPct": 5,  "lockHwPct": 35, "consecutiveBreachesRequired": 3},
    {"triggerPct": 10, "lockHwPct": 55, "consecutiveBreachesRequired": 2},
    {"triggerPct": 15, "lockHwPct": 75, "consecutiveBreachesRequired": 1},
    {"triggerPct": 20, "lockHwPct": 88, "consecutiveBreachesRequired": 1}
  ]
}
```

**FALLBACK:** Use `tiersLegacyFallback` from config until engine supports `pct_of_high_water`.

---

## The Three Amplifications

### 1. High Water Geometry: Tighter on Runners

VIPER's agent said High Water Mode was "by far the biggest driver of profitability." ANACONDA tightens the geometry on the upper tiers to capture even more of each runner:

| Tier | VIPER | ANACONDA | Difference |
|---|---|---|---|
| T1 (+5% ROE) | 30% of HW | **35% of HW** | Slightly tighter — protect range profits earlier |
| T2 (+10% ROE) | 50% of HW | **55% of HW** | |
| T3 (+15% ROE) | 70% of HW | **75% of HW, 1 breach** | Tighter + instant exit (VIPER uses 2 breaches) |
| T4 (+20% ROE) | 85% of HW | **88% of HW, 1 breach** | Maximum lock — keeps 88% of every runner |

At +22% ROE (the ETH trade the agent referenced): VIPER locks +18.7% (85%). ANACONDA locks +19.4% (88%). Small per-trade, compounds over dozens of trades.

### 2. Conviction-Scaled Phase 1: Wider for High Scores

VIPER's agent said conviction scaling "stopped us getting chopped out of our best setups." ANACONDA pushes this further — high-score entries get maximum breathing room:

| Score | VIPER Floor | ANACONDA Floor |
|---|---|---|
| 5-6 | -15% ROE | **-15% ROE** (same — marginal setups stay on short leash) |
| 7-8 | -20% ROE | **-25% ROE** (more room for confirmed setups) |
| 9+ | Unrestricted | **Unrestricted** (same — elite setups get max room) |

The gap is in the middle tier. Score 7-8 entries are good-but-not-elite — they're the ones that were getting chopped by the old -20% floor on normal market maker wicks. ANACONDA gives them 25% room.

### 3. OI Floor: Higher Minimum, Deeper Liquidity Only

VIPER's agent said USD-weighted OI filtering "eliminated noise of illiquid altcoins." ANACONDA raises the floor:

| Setting | VIPER | ANACONDA |
|---|---|---|
| Min OI (USD-weighted) | $5M | **$10M** |
| Assets scanned | Top 25 | **Top 15** (only deepest liquidity) |

Fewer candidates, but every one has the depth to respect maker exits without slippage. The ETH and BTC range trades that drove VIPER's #2 ranking all had $50M+ OI — the $5-10M altcoin trades were the ones that slipped and lost.

---

## What Else Changed vs VIPER

| Variable | VIPER | ANACONDA | Why |
|---|---|---|---|
| **Min score** | 5 | **6** | Slightly higher bar — only confirmed range setups |
| **Margin per trade** | 28% | **30%** | More capital per trade — fewer but better candidates |
| **Max positions** | 3 | **2** | Concentrated in deep-liquidity plays |
| **Stagnation TP** | 5% ROE, 30min | **8% ROE, 45min** | More patience — deep liquidity ranges resolve cleaner |
| **Max entries/day** | 8 | **6** | Quality over quantity |
| **BB width max** | 4% | **3.5%** | Tighter ranges only — cleaner bounces |

---

## Config Override File

```json
{
  "basedOn": "viper-2.1",
  "version": "1.0",
  "name": "Anaconda",
  "description": "Deep liquidity range hunter — amplified High Water, wider conviction Phase 1, $10M OI floor",

  "entry": {
    "maxBbWidthPct": 3.5,
    "maxAtrPct": 1.5,
    "rsiOversold": 35,
    "rsiOverbought": 65,
    "minScore": 6,
    "marginPct": 0.30,
    "minOiUsd": 10000000,
    "maxCandidates": 15,
    "dynamicSlots": {
      "enabled": true,
      "baseMax": 4,
      "absoluteMax": 6,
      "unlockThresholds": [
        {"pnl": 75, "maxEntries": 5},
        {"pnl": 200, "maxEntries": 6}
      ]
    }
  },

  "dsl": {
    "_spec": "https://github.com/Senpi-ai/senpi-skills/blob/main/dsl-dynamic-stop-loss/dsl-high-water-spec%201.0.md",
    "lockMode": "pct_of_high_water",
    "phase2TriggerRoe": 5,
    "phase1HardTimeoutMin": 0,
    "phase1WeakPeakMin": 0,
    "phase1DeadWeightMin": 0,
    "floorBase": 0.015,
    "convictionTiers": [
      {"minScore": 5, "absoluteFloorRoe": -15, "hardTimeoutMin": 0, "weakPeakCutMin": 0, "deadWeightCutMin": 0},
      {"minScore": 7, "absoluteFloorRoe": -25, "hardTimeoutMin": 0, "weakPeakCutMin": 0, "deadWeightCutMin": 0},
      {"minScore": 9, "absoluteFloorRoe": 0,   "hardTimeoutMin": 0, "weakPeakCutMin": 0, "deadWeightCutMin": 0}
    ],
    "tiers": [
      {"triggerPct": 5,  "lockHwPct": 35, "consecutiveBreachesRequired": 3},
      {"triggerPct": 10, "lockHwPct": 55, "consecutiveBreachesRequired": 2},
      {"triggerPct": 15, "lockHwPct": 75, "consecutiveBreachesRequired": 1},
      {"triggerPct": 20, "lockHwPct": 88, "consecutiveBreachesRequired": 1}
    ],
    "tiersLegacyFallback": [
      {"triggerPct": 3,  "lockPct": 1},
      {"triggerPct": 5,  "lockPct": 3},
      {"triggerPct": 8,  "lockPct": 5, "retrace": 0.012},
      {"triggerPct": 12, "lockPct": 9, "retrace": 0.010},
      {"triggerPct": 18, "lockPct": 14, "retrace": 0.008},
      {"triggerPct": 25, "lockPct": 21, "retrace": 0.006}
    ],
    "stagnationTp": {
      "enabled": true,
      "roeMin": 8,
      "hwStaleMin": 45
    }
  },

  "risk": {
    "maxEntriesPerDay": 6,
    "maxDailyLossPct": 8,
    "maxDrawdownPct": 18,
    "maxSingleLossPct": 5,
    "maxPositions": 2,
    "maxConsecutiveLosses": 3,
    "cooldownMinutes": 30
  },

  "execution": {
    "entryOrderType": "FEE_OPTIMIZED_LIMIT",
    "entryEnsureTaker": true,
    "exitOrderType": "MARKET",
    "slOrderType": "MARKET",
    "takeProfitOrderType": "FEE_OPTIMIZED_LIMIT"
  }
}
```

---

## VIPER Family Comparison

| | VIPER | MAMBA | ANACONDA |
|---|---|---|---|
| **Thesis** | Range bounce | Range bounce + breakout escape | **Range bounce in deep liquidity** |
| **OI floor** | $5M | $5M | **$10M** |
| **Assets scanned** | Top 25 | Top 25 | **Top 15** |
| **HW T4 lock** | 85% | 85% | **88%** |
| **HW T3 breaches** | 2 | 2 | **1 (instant)** |
| **Phase 1 mid-tier** | -20% ROE | -20% ROE | **-25% ROE** |
| **Max positions** | 3 | 3 | **2** |
| **Best for** | All ranges | Ranges that might break out | **High-liquidity ranges (BTC, ETH, SOL ranges)** |

VIPER is the broadest. MAMBA adds breakout capture. ANACONDA concentrates on the deepest, cleanest ranges and squeezes more from each trade.

---

## Expected Behavior

| Metric | VIPER | ANACONDA (expected) |
|---|---|---|
| Trades/day | 3-8 | **2-5** (higher OI floor = fewer candidates) |
| Win rate | ~60-65% | **~62-68%** (deeper liquidity = cleaner bounces) |
| Avg winner | 5-15% ROE | **6-18% ROE** (88% HW lock captures more) |
| Avg loser | -8 to -12% ROE | **-10 to -15% ROE** (wider mid-tier floors) |
| Fee drag/day | $8-20 | **$5-15** |
| Profit factor | 1.2-1.5 | **Target 1.4-1.8** |

---

## Notification Policy

**ONLY alert:** Position OPENED or CLOSED, risk triggered, critical error.
**NEVER alert:** Scanner found nothing, DSL routine, any reasoning.
All crons isolated. `NO_REPLY` for idle cycles.

---

## Deployment

ANACONDA runs on VIPER v2.1. Deploy VIPER, then apply these overrides.
