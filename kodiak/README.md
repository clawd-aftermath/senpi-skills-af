# 🐻 KODIAK v1.0 — SOL Alpha Hunter

Part of the [Senpi Trading Skills Zoo](https://github.com/Senpi-ai/senpi-skills).

## What KODIAK Does

KODIAK is a single-asset alpha hunter for **SOL** on Aftermath Finance. It uses every available signal source (SM positioning, funding, OI, 4-timeframe trend, volume, BTC correlation) to build a conviction thesis, then trades it with 7-12x leverage and DSL High Water trailing stops.

Based on GRIZZLY v2.0's three-mode lifecycle, adapted for SOL's volatility profile.

## Three-Mode Lifecycle

```
HUNTING ──> enter ──> RIDING ──> DSL closes ──> STALKING
   ^                    |                          |
   |                    v                          v
   |              thesis breaks              reload OR kill
   |              (reset to HUNT)           (reload=RIDE, kill=HUNT)
   +───────────────────────────────────────────────+
```

- **HUNTING:** Scan every 3 min. Score 10+ across all signals to enter.
- **RIDING:** Position open. DSL trails. Thesis re-evaluated every scan.
- **STALKING:** DSL took profit. Watch for reload on dip, or kill if thesis dies.

## Quick Start

1. Deploy `config/kodiak-config.json` to your Senpi agent
2. Deploy `scripts/kodiak-scanner.py` and `scripts/kodiak_config.py`
3. Create scanner cron (3 min, isolated) and DSL cron (3 min, isolated)
4. Fund with $1,000 on the Senpi Predators leaderboard

## Directory Structure

```
kodiak-v1.0/
|-- README.md
|-- SKILL.md
|-- config/
|   +-- kodiak-config.json
+-- scripts/
    |-- kodiak-scanner.py
    +-- kodiak_config.py
```

## Key Config Differences from GRIZZLY (BTC)

| Setting | GRIZZLY (BTC) | KODIAK (SOL) |
|---|---|---|
| Asset | BTC | SOL |
| Correlation | ETH | BTC |
| Leverage | 12-20x | 7-12x |
| Margin base | 30% | 20% |
| DSL floor | 3.5% notional | 2.5% notional |
| Stagnation TP | 12% ROE / 90 min | 10% ROE / 75 min |

## Entry Requirements (all must pass)

| Gate | Requirement |
|---|---|
| 4h trend | Bullish or bearish structure (required) |
| 1h trend | Must agree with 4h (required) |
| 15m momentum | Must confirm direction (required) |
| SM positioning | Hard block if opposing |
| Score | >= 10 combined |

## License

MIT — see root repo LICENSE.
