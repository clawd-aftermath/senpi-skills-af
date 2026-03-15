# 🐋 Whale Index

**Auto-mirror top Discovery traders on Aftermath Finance.**

Whale Index scans the top 50 traders on Aftermath's Discovery leaderboard, scores them on a weighted composite (PnL rank, win rate, consistency, hold time, drawdown), and creates 2-5 mirror strategies sized to your budget. A daily cron monitors performance and swaps underperformers — but only after a 2-day watch period to avoid churn from temporary dips.

## How It Works

1. **Onboard** — Tell the agent your budget and risk tolerance (conservative / moderate / aggressive). Budget determines how many mirror slots you get (2-5). Risk level controls which trader tiers are eligible and max leverage.

2. **Discover** — The agent pulls the top 50 Discovery traders, filters by your risk profile, and scores each candidate:

   `0.35 × PnL rank + 0.25 × win rate + 0.20 × consistency + 0.10 × hold time + 0.10 × drawdown`

   Overlap check flags when selected traders share >50% of the same positions.

3. **Allocate** — Score-weighted allocation across your slots, capped at 35% per trader to enforce diversification.

4. **Execute** — Creates mirror strategies with strategy-level stop losses (-10% / -15% / -25% depending on risk level). You approve the lineup before anything goes live.

5. **Monitor** — Daily cron checks every mirrored trader. If a trader drops below rank 50, goes inactive for 48h+, or hits 2× historical drawdown, they enter a 2-day watch period. Only after sustained degradation AND a better alternative scoring ≥15% higher does the agent swap.

## Quick Start

```
You: "Set up Whale Index with $5,000, moderate risk"
Agent: [reads SKILL.md] → [scans Discovery] → [scores & filters] → [presents lineup] → [you approve] → [mirrors are live]
```

## Risk Levels

| Level | Eligible Traders | Max Leverage | Strategy Stop Loss |
|-------|-----------------|-------------|-------------------|
| Conservative | ELITE only | 10x | -10% |
| Moderate | ELITE + RELIABLE | 15x | -15% |
| Aggressive | ELITE + RELIABLE + BALANCED | 25x | -25% |

## Budget → Slots

| Budget | Mirror Slots |
|--------|-------------|
| $500 – $2k | 2 |
| $2k – $5k | 3 |
| $5k – $10k | 4 |
| $10k+ | 5 |

## Senpi MCP Tools Used

- `discovery_top_traders` — pull leaderboard data
- `strategy_create_mirror` — create mirror strategies
- `strategy_get_clearinghouse_state` — check positions & overlap
- `strategy_close_strategy` — teardown when exiting

## File Structure

```
whale-index/
├── SKILL.md                        # Agent playbook
├── README.md                       # This file
└── references/
    └── daily-monitoring.md         # Full daily cron procedure & swap logic
```

## Teardown

Tell the agent to exit Whale Index. It closes all mirror strategies and returns funds to your main wallet.

## Fee Estimates

Mirror strategies incur the same fees as the mirrored trader's activity. Budget ~0.5-1% daily for active traders.

## License

Apache-2.0
