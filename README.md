# Senpi Skills — The Home of Aftermath Finance Agents

22 AI trading skills. 13 trading strategies. 30+ scanners. All open source. All tracked live.

Senpi Skills is the open source repository for autonomous trading strategies on [Aftermath Finance](https://aftermath.finance) via [Senpi](https://senpi.ai). Each skill is a self-contained trading agent that scans markets 24/7, enters and exits positions, manages trailing stops, and protects capital — autonomously.

**Live tracker:** [strategies.senpi.ai](https://strategies.senpi.ai) — every skill running with real money, full transparency.

## Skills (22 unique trading agents)

### Momentum & Leaderboard
| Skill | Description | Scanner Interval |
|---|---|---|
| 🦊 [FOX](./fox) | Explosive breakout sniper. Catches First Jumps on the leaderboard before the crowd. **#1 at +34.5% ROI.** | 3 min |
| 🦊 [VIXEN](./vixen) | **NEW.** Dual-mode SM sniper. STALKER mode catches quiet accumulation before the explosion. STRIKER mode catches violent breakouts with volume confirmation. Built from FOX's live data. | 90 sec |
| 🐺 [WOLF](./wolf-strategy) | Pack hunter. Leaderboard momentum, enters early on what smart money is buying. | 3 min |
| 🦅 [HAWK](./hawk-trading-bot) | Scans BTC, ETH, SOL, HYPE every 30 seconds. Picks the single strongest signal. | 30 sec |

### Single-Asset Hunters (The Bear Family + Wolverine)
| Skill | Description | Scanner Interval |
|---|---|---|
| 🐻 [GRIZZLY](./grizzly) | BTC only. Every signal source. 12-20x leverage. Three-mode lifecycle: HUNTING → RIDING → STALKING → RELOAD. **#2 at +11.2% ROI.** | 3 min |
| 🐻‍❄️ [POLAR](./polar) | **NEW.** ETH alpha hunter. Grizzly's three-mode lifecycle adapted for ETH. BTC as correlation confirmation. 10-15x leverage. | 3 min |
| 🐻 [KODIAK](./kodiak) | **NEW.** SOL alpha hunter. Grizzly's three-mode lifecycle adapted for SOL. 7-12x leverage. Tuned for SOL's higher volatility. | 3 min |
| 🦡 [WOLVERINE](./wolverine) | **NEW.** HYPE alpha hunter. Grizzly's three-mode lifecycle adapted for HYPE. 5-10x leverage. Aggressive DSL trailing for HYPE's speed. BTC correlation is bonus-only (HYPE moves independently). | 3 min |
| 🐆 CHEETAH | HYPE only. 8-12x leverage. Fastest predator for the fastest asset. | 3 min |

### Multi-Signal Convergence
| Skill | Description | Scanner Interval |
|---|---|---|
| 🐅 [TIGER](./tiger-strategy) | 5 parallel scanners, 230 assets, ROAR meta-optimizer that learns from results. Paused at -58%. | 5 min |
| 🐍 [COBRA](./cobra) | Triple convergence. Only strikes when price, volume, and new money all agree. | 3 min |
| 🦬 [BISON](./bison) | Conviction holder. Top 10 assets, 4h trend thesis, holds hours to days. **v1.1: unlimited batch reloads when profitable.** | 5 min |

### Range & Technical
| Skill | Description | Scanner Interval |
|---|---|---|
| 🐍 [VIPER](./viper) | Range-bound mean reversion at support/resistance. Works when nothing is trending. | 5 min |
| 🐆 PANTHER | BB squeeze breakout scalper. Fastest cuts in the zoo. | 2 min |
| 🦅 EAGLE | Correlation breaks + macro events. BTC/ETH vs alts divergence. | 3 min |

### Alternative Edge
| Skill | Description | Scanner Interval |
|---|---|---|
| 🦉 [OWL](./owl) | Pure contrarian. Enters against extreme crowding when exhaustion signals fire. **v5.2: funding floor fix lets the five-factor model actually run.** | 15 min |
| 🦈 [SHARK](./shark) | SM consensus + liquidation cascade front-running. | 5 min |
| 🐊 [CROC](./croc) | Funding rate arbitrage. Collects payments while waiting for the snap. | 15 min |
| 🦎 [KOMODO](./komodo) | **NEW.** Momentum event consensus. Uses real-time `leaderboard_get_momentum_events` to detect SM convergence. Replaces Mantis v1.0 and Scorpion v1.1. | 5 min |

### Upgraded / Redirected
| Skill | Status |
|---|---|
| 🦗 [MANTIS](./mantis) | **Now powered by VIXEN v1.0.** Original whale-mirroring scanner retired (stale position data). See [vixen/](./vixen). |
| 🦂 [SCORPION](./scorpion) | **Deprecated.** Same stale-position problem as Mantis v1.0 with looser filters. 406 trades, -24.2% ROI. Replaced by [KOMODO](./komodo). |

## Trading Strategies (13 config overrides)

Trading strategies run on a parent skill's scanner with different entry filters, DSL settings, and risk parameters. Same code, different personality.

### On FOX
| Strategy | What Changes |
|---|---|
| 🦊 [FERAL FOX](./feral-fox-strategy%201.2.md) | Score 7+, 3 reasons, regime enforced, structural invalidation, no time exits |
| 👻 [GHOST FOX](./ghost-fox-strategy%20(1).md) | Feral Fox entries + DSL High Water Mode infinite trailing at 85% of peak |
| 🐱 LYNX | Patient high-bar momentum. Score 10+, wide stops, no time exits. The proven pattern. |
| 🐺 JACKAL | FOX v1.6 scanner + RHINO pyramiding (30/40/30 stages). |

### On WOLF
| Strategy | What Changes |
|---|---|
| 🐺 [DIRE WOLF](./wolf-strategy) | Replaces WOLF config entirely. FIRST_JUMP only, zero rotation, maker fees, DSL High Water. |

### On TIGER
| Strategy | What Changes |
|---|---|
| 🦁 LION | Patient multi-scanner. Stricter confluence, scanner weighting, no time exits, drawdown auto-resume. |

### On VIPER
| Strategy | What Changes |
|---|---|
| 🐍 [MAMBA](./mamba-strategy%20(1).md) | Viper entries + DSL High Water. Catches the range bounce AND the breakout that escapes. |
| 🐍 ANACONDA | $10M OI floor, 88% HW lock, wider Phase 1. |

### On CROC
| Strategy | What Changes |
|---|---|
| 🐊 GATOR | Patient funding arb. No time exits, structural thesis exits only (funding flip = dead), funding income tracking. |

## The Proven Pattern

Across all 22 skills and 13 strategies, one pattern dominates: **fewer trades + higher conviction + wider stops = better performance.**

| Skill | Trades | ROI | The lesson |
|---|---|---|---|
| 🦊 FOX | 91 | **+34.5%** | Selective entries, let winners run |
| 🐻 GRIZZLY | 24 | **+11.2%** | Single asset, maximum conviction |
| 🦬 BISON | 118 | **+5.3%** | Thesis-based holds |
| 🐅 TIGER | 726 | **-58%** | Over-trading kills |
| 🐊 CROC | 535 | **-42.9%** | Fee drag is the silent killer |
| 🦂 SCORPION | 420 | **-24.2%** | Stale data + loose filters |

Every winning skill upgrade has tightened entry filters, not stop losses.

## New Skills (March 2026)

### 🦊 VIXEN — Dual-Mode SM Sniper
Two entry modes built from FOX's live trading data:
- **STALKER:** Catches SM quietly accumulating over 3+ scans before the explosion (the ZEC/SILVER pattern — +$129/+$128 entries at score 5-7)
- **STRIKER:** Catches violent FIRST_JUMP breakouts with raw volume confirmation (filters blow-off tops like PUMP)

Plus: 2-hour per-asset cooldown after Phase 1 exits. Volume gate on Striker mode. Time-of-day scoring.

### 🐻‍❄️ POLAR / 🐻 KODIAK / 🦡 WOLVERINE — The Bear Family Expands
Grizzly's three-mode lifecycle (HUNTING → RIDING → STALKING → RELOAD) adapted for ETH, SOL, and HYPE. Each tuned for its asset's volatility — lower leverage on higher-vol assets, tighter DSL for faster movers. Wolverine v1.1 has HYPE-specific aggressive DSL trailing after day 1 data showed the original tiers were too loose for HYPE's reversal speed.

### 🦎 KOMODO — Momentum Event Consensus
Uses `leaderboard_get_momentum_events` (real-time threshold crossings) instead of `discovery_get_top_traders` (stale positions). When 2+ quality SM traders cross momentum thresholds on the same asset/direction, confirmed by market concentration and volume, KOMODO enters with the momentum. Five-gate entry model.

## Shared Infrastructure

These are plugins used by all skills automatically. Users don't need to install them separately.

| Plugin | Purpose |
|---|---|
| [DSL Dynamic Stop Loss](./dsl-dynamic-stop-loss) | Trailing stop engine. Supports fixed ROE tiers and [High Water Mode](./dsl-dynamic-stop-loss/dsl-high-water-spec%201.0.md) (percentage-of-peak locks). |
| [Fee Optimizer](./fee-optimizer) | When to use ALO vs MARKET, standard order params, fee computations (FDR, maker %). |
| [Senpi Onboard](./senpi-onboard) | Agent onboarding and account setup. |
| [Getting Started Guide](./senpi-getting-started-guide) | Interactive first-trade tutorial. |
| [Emerging Movers](./emerging-movers) | Leaderboard scanner shared by FOX, WOLF, and VIXEN. |
| [Opportunity Scanner](./opportunity-scanner) | Deep 4-stage funnel scanner for FOX. |

## DSL High Water Mode

The trailing stop configuration proven across the zoo. Instead of locking fixed ROE amounts, High Water Mode locks a percentage of the peak. The stop trails at 85-90% of the highest ROE the trade has ever reached, with no ceiling.

**Full spec:** [dsl-high-water-spec 1.0.md](./dsl-dynamic-stop-loss/dsl-high-water-spec%201.0.md)

**Adoption guide (all skills):** [dsl-high-water-adoption-guide.md](./dsl-dynamic-stop-loss/dsl-high-water-adoption-guide.md)

All active skills use High Water Mode as default.

## Architecture

```
Plugins ──→ Skills ──→ Trading Strategies
(shared)     (scanner)   (config override)
```

**Plugins** are shared infrastructure — trailing stops, risk management, fee optimization. Maintained once, every skill benefits.

**Skills** are the trading logic — the scanner that embodies a thesis about how to make money. FOX's First Jump detector. VIPER's range analysis. OWL's crowding exhaustion. VIXEN's dual-mode accumulation/explosion detection. Each skill is a thin layer on top of shared plugins.

**Trading Strategies** are saved configurations — the specific numbers that tune how aggressively a skill behaves. LYNX is FOX's scanner with score 10+ filters. LION is TIGER's scanners with no time exits. The skill is the predator. The strategy is how you teach it to hunt.

## Quick Start

1. Deploy [OpenClaw](https://openclaw.ai) with [Senpi](https://senpi.ai) MCP configured
2. Install a skill: `npx skills add Senpi-ai/senpi-skills/<skill-name>`
3. The agent reads SKILL.md, runs bootstrap, creates crons, and starts trading
4. Monitor via Telegram alerts and [strategies.senpi.ai](https://strategies.senpi.ai)

**Recommended first skill:** VIXEN — dual-mode scanner with the best risk management in the zoo.

## Requirements

- [OpenClaw](https://openclaw.ai) agent with cron support
- [Senpi](https://senpi.ai) MCP access token
- Sui strategy wallet funded with USDC collateral
- Python 3.8+ (no external dependencies — all skills use stdlib only)

## Contributing

Each skill is self-contained in its own directory. Trading strategies are config override files (JSON + markdown spec). See any skill's SKILL.md for the full agent instructions.

All skills use [DSL High Water Mode](./dsl-dynamic-stop-loss/dsl-high-water-spec%201.0.md) as the target trailing stop configuration. See the [adoption guide](./dsl-dynamic-stop-loss/dsl-high-water-adoption-guide.md) for per-skill tier tables.

**When adding a new skill**, add an entry to [`catalog.json`](./catalog.json). This file is the machine-readable registry used by the onboarding agent to present skills to users. Each entry needs an `id`, `name`, `emoji`, `tagline`, `group`, and `sort_order` — see existing entries for reference.

## License

MIT — Built by [Senpi](https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
