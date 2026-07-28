---
name: aftermath-perpetuals
description: Practical skill for integrating Aftermath Perpetuals with native endpoints as the default (full feature set), plus CCXT-compatible endpoints and the TypeScript SDK.
version: 3.0.0-rc.1
capabilities:
  - api-integration
  - sdk-integration
  - order-placement
  - position-monitoring
  - risk-analysis
  - vault-management
  - error-handling
---

# Aftermath Perpetuals Skill

Verified against post-relaunch OpenAPI: `https://v2-preview.aftermath.finance/api/openapi/spec.json`
Last validated: `2026-07-28`
Canonical docs UI: `https://v2-preview.aftermath.finance/docs`
API base: `https://v2-preview.aftermath.finance/api`

## Fast Routing

Choose one file first; do not load everything by default.

Default preference: start with native perpetuals endpoints (`/api/perpetuals/*`) because they expose the full Aftermath feature set. Use CCXT endpoints when you specifically need exchange-style compatibility.

1. CCXT endpoint work -> `ccxt.md`
2. Native perpetuals endpoint work -> `native.md`
3. SDK method usage -> `sdk-reference.md`
4. API failures/retries -> `error-handling.md`
5. Trading safeguards -> `safety-and-risk.md`
6. Builder codes/gas pool/referrals/rewards/coins utility routes -> `auxiliary-endpoints.md`
7. Edge-case pitfalls -> `gotchas.md`
8. Market making optimization, gas efficiency, cancel-and-place -> `market-making.md`

## Integration Modes

Preferred by default: Native perpetuals (`/api/perpetuals/*`) for complete API coverage.

| Mode | Best for | Primary file |
|---|---|---|
| CCXT compatibility (`/api/ccxt/*`) | Exchange-style payloads and build-sign-submit bots | `ccxt.md` |
| Native perpetuals (`/api/perpetuals/*`) | Full account/vault previews + tx builders | `native.md` |
| TypeScript SDK (`@aftermath-finance/sdk`) | Typed app integrations | `sdk-reference.md` |

## High-Risk Guardrails

- Sign `signingDigest`, not `transactionBytes`.
- Keep ID types strict: CCXT write `accountId` (object ID) vs native `accountId` (numeric).
- Treat preview responses as success/error unions.
- Re-sync snapshots after stream reconnect before applying deltas.
- Serialize coin/gas-object-sensitive operations to avoid version conflicts.

## Recent API Updates

- Candle history uses `resolution` (`1m`, `15m`, `1h`, etc.) with
  `fromTimestamp` / `toTimestamp`; the legacy millisecond interval field is gone.
- Native and CCXT order builders support client-managed order IDs.
- SL/TP inputs use `stopLossPrice`, `takeProfitPrice`, and `triggerPriceType`.
- Native account and vault APIs expose TWAP create/edit/cancel/data routes.
- Builder codes now use numeric integrator IDs and registration routes; the old
  integrator-vault read/create/claim routes are not part of the relaunch spec.
- Native account/vault routes include `place-scale-order`, `cancel-and-place-orders`, and account `share` transaction support.
- Account history now includes both `orders` (order history) and detailed `trades` / CSV export routes.
- Margin history requests use `timeframe` (`1D | 1W | 1M | ALL`) with `accountId`.
- Stop-order data requests support optional `marketIds` filtering.
- Vault owner flows include locked-liquidity withdraw routes and a preview route for pausing force-withdraw processing.
- CCXT submit supports one-or-more `signatures` when sender and gas owner differ.
- Rewards endpoints include signed points lookups, and auxiliary docs now cover the gas pool service.
- **Gas Pool sponsorship**: Pre-fund a gas pool, deposit SUI or USDC (auto-swaps), grant agent wallets, trade with `sponsor` field.
- **USDC as gas**: Deposit USDC into GasPool — auto-swaps to SUI via Aftermath router. Agent wallets never need SUI.

## Progressive Disclosure

| File | Read when |
|---|---|
| `ccxt.md` | You need `/api/ccxt/*` endpoints or stream setup |
| `native.md` | You need `/api/perpetuals/*` account/market/vault APIs |
| `auxiliary-endpoints.md` | You need builder-codes, gas pool, referrals, rewards, coins, utility txs |
| `sdk-reference.md` | You are coding with SDK classes and methods |
| `error-handling.md` | You are implementing retry, backoff, and failure parsing |
| `safety-and-risk.md` | You are shipping a bot or live strategy safeguards |
| `gotchas.md` | You need a pre-launch pitfalls checklist |
| `market-making.md` | You are building an MM bot or optimizing gas for quoting |

## Source of Truth

- Site: `https://v2-preview.aftermath.finance`
- Swagger: `https://v2-preview.aftermath.finance/docs`
- OpenAPI: `https://v2-preview.aftermath.finance/api/openapi/spec.json`
- Maintained skills: `https://github.com/AftermathFinance/skills`

The current OpenAPI document still advertises production/testnet servers. For
post-relaunch integration work, use the explicit v2-preview base above until the
relaunch host becomes the public production host. This skill is versioned as a
release candidate while that preview host is canonical.

Run the contract check after changing API examples or scripts:

```bash
python3 aftermath-perpetuals/scripts/check_api_contract.py
```

The default check intentionally fetches the live preview spec and reports its
canonical JSON SHA-256, so it detects API drift. For a reproducible check
against a reviewed snapshot, download the spec outside the repository and pass
it explicitly:

```bash
python3 aftermath-perpetuals/scripts/check_api_contract.py --spec /path/to/spec.json
```
