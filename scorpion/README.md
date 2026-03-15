# 🦂 SCORPION v2.0 — Momentum Event Consensus

Part of the [Senpi Trading Skills Zoo](https://github.com/Senpi-ai/senpi-skills).

## What SCORPION v2.0 Does

SCORPION v2.0 detects real-time smart money convergence on Aftermath Finance using `leaderboard_get_momentum_events`. When 2+ quality traders cross momentum thresholds ($2M+/$5.5M+/$10M+) on the same asset and direction within 60 minutes, confirmed by market concentration and volume, SCORPION enters with the momentum.

**This is a complete rewrite.** SCORPION v1.1 mirrored whale positions using stale data (406 trades, -24.2% ROI). v2.0 follows smart money ACTIONS, not stale positions.

## Five-Gate Entry Model

```
Momentum Events (2+ traders on same asset/direction)
        ↓
Trader Quality (Elite/Reliable TCS, no Degen)
        ↓
Market Confirmation (5+ traders active via leaderboard_get_markets)
        ↓
Volume Confirmation (1h vol ≥ 50% of 6h avg)
        ↓
Regime Filter (penalty for counter-trend, not a block)
        ↓
Score ≥ 10 → ENTER
```

## Quick Start

1. Deploy `config/scorpion-config.json` to your Senpi agent
2. Deploy `scripts/scorpion-scanner.py` and `scripts/scorpion_config.py`
3. Create scanner cron (5 min, isolated) and DSL cron (3 min, isolated)
4. Fund with $1,000 on the Senpi Predators leaderboard

## Directory Structure

```
scorpion-v2.0/
├── README.md
├── SKILL.md
├── config/
│   └── scorpion-config.json
└── scripts/
    ├── scorpion-scanner.py
    └── scorpion_config.py
```

## License

MIT — see root repo LICENSE.
