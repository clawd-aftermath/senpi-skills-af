# 🐋 ORCA v1.0 — Hardened Dual-Mode Scanner

Part of the [Senpi Trading Skills](https://github.com/Senpi-ai/senpi-skills).

## What ORCA Does

ORCA is the definitive version of the Vixen/Fox dual-mode emerging movers scanner. Every lesson from 5 days of live trading across 22 agents is hardcoded into the scanner itself — not in agent instructions that can be ignored or self-modified.

Fox's exact winning config (+23.2% ROI). Every protective gate in the code.

## Why Not Just Run Vixen?

Three agents ran the same Vixen scanner. Fox: +23.2%. Mantis: -6.5%. Vixen: -17.3%. The difference was config drift — agents removed stagnation TP, raised daily loss limits, and traded XYZ equities. ORCA prevents this by putting the gates in the Python code, not the config.

## Hardcoded in the Scanner

- XYZ equities filtered at scan parse level (never enter the signal pipeline)
- Leverage constraints (7-10x) in scanner output
- Stagnation TP, daily loss limit, asset cooldown all in output constraints block
- Agent cannot override — signals that violate gates simply don't appear

## Quick Start

1. Deploy `config/orca-config.json` to your Senpi agent
2. Deploy `scripts/orca-scanner.py` and `scripts/orca_config.py`
3. Create scanner cron (90s, main) and DSL cron (3 min, isolated)
4. Fund with $1,000

## Directory Structure

```
orca-v1.0/
├── README.md
├── SKILL.md
├── config/
│   └── orca-config.json
└── scripts/
    ├── orca-scanner.py
    └── orca_config.py
```

## License

MIT — see root repo LICENSE.
