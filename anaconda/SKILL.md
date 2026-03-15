---
name: anaconda-strategy
description: >-
  ANACONDA — Deep liquidity range hunter. Trading strategy on VIPER v2.1.
  Amplifies VIPER's three winning mechanics: tighter High Water geometry (88% lock),
  wider conviction Phase 1 (-25% mid-tier), higher OI floor ($10M).
  Fewer candidates, deeper liquidity, more captured per trade.
license: MIT
metadata:
  author: jason-goldberg
  version: "1.0"
  platform: senpi
  exchange: aftermath
  base_skill: viper-2.1
  type: trading-strategy
---

# ANACONDA — Deep Liquidity Range Hunter

Trading strategy override on VIPER v2.1. Same scanner, same range detection — different config that amplifies what's working.

**Requires:** VIPER v2.1 must be installed first. ANACONDA applies `config.json` overrides on top.

## How to Deploy

1. Install VIPER v2.1 from the senpi-skills repo
2. Apply ANACONDA's `config.json` overrides to the VIPER config
3. Agent uses VIPER's scanner with ANACONDA's entry filters, DSL tiers, and risk params

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

**FALLBACK:** Use `tiersLegacyFallback` from `config.json` until engine supports `pct_of_high_water`.

## Key Overrides vs VIPER

| Setting | VIPER | ANACONDA |
|---|---|---|
| OI floor | $5M | **$10M** — deep liquidity only |
| Assets scanned | Top 25 | **Top 15** |
| BB width max | 4% | **3.5%** — tighter ranges only |
| Min score | 5 | **6** |
| Margin per trade | 28% | **30%** |
| Max positions | 3 | **2** — concentrated |
| HW T3 lock | 70%, 2 breaches | **75%, 1 breach (instant)** |
| HW T4 lock | 85% | **88%** |
| Phase 1 mid-tier floor | -20% ROE | **-25% ROE** |
| Stagnation TP | 5% ROE, 30min | **8% ROE, 45min** |

All config values are in `config.json`. The agent reads them and applies to VIPER's scanner output.

## Notification Policy

Same as VIPER. ONLY alert on position OPENED or CLOSED, risk triggered, critical error. NO_REPLY for idle cycles.

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
