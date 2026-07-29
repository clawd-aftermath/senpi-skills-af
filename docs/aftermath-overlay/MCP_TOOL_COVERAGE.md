# MCP tool coverage

The upstream strategy packages call Senpi MCP tools. The adapter
(`aftermath_runtime/adapter.py`) presents that same surface and serves it from
Aftermath V2, which is why all 99 packages run without being individually
ported.

Machine-readable source of truth: `aftermath_runtime/toolspec.py`.
Print it live with `python3 -m aftermath_runtime coverage`.

## How the surface was enumerated

Every `strategies/**/*.py` was parsed for `call_tool("<name>", …)`. That yields
**nine** tools, marked ★ below — the ones a scanner actually invokes at runtime.
The remaining names were collected from the lifecycle and analysis skills
(`senpi-strategy-ops`, `senpi-portfolio`, `senpi-improve-trades`, …), which
drive the same MCP surface from the agent side.

## Status legend

| status | meaning |
|---|---|
| `implemented` | fully served from Aftermath V2 routes |
| `degraded` | served, but a documented part of the upstream payload has no Aftermath equivalent and is **omitted rather than faked** |
| `build_only` | a mutation. Built, previewed and inspected; never signed or submitted. Refused unless armed. |
| `unavailable` | Aftermath genuinely has no such data. Raises `CapabilityUnavailable`. Never returns a plausible substitute. |

**Totals: 10 implemented · 6 degraded · 9 build-only · 10 unavailable = 35.**

## Called directly by strategy scanners

| ★ tool | status | backed by |
|---|---|---|
| `market_get_asset_data` | implemented | `all-markets` + `markets/prices` + `markets/24hr-stats` + `market/candle-history` + `markets/orderbooks` |
| `market_list_instruments` | implemented | `all-markets` |
| `market_get_funding_history` | implemented | `market/funding-history` |
| `market_get_funding_regime` | implemented | `all-markets` + `market/funding-history` |
| `strategy_get_open_orders` | implemented | `ccxt/myPendingOrders` |
| `audit_query` | implemented | `account/order-history` (cursor-paginated) |
| `strategy_get_clearinghouse_state` | degraded | `accounts/owned` + `accounts/positions` |
| `leaderboard_get_markets` | **unavailable** | — |
| `market_get_cross_asset_flows` | **unavailable** | — |

### The two that cannot be served, and what happens

`leaderboard_get_markets` is a smart-money positioning feed: per-asset long/short
tilt across ranked traders. `market_get_cross_asset_flows` is capital rotation
computed from the same trader-level data. **Aftermath publishes no cross-account
trader positioning at all**, and there is no route that could be bent into one.

Strategies that gate on these are read-guarded upstream: the call raises, the
gate fails, the strategy skips its tick. That is the correct outcome — it is the
strategy declining to trade on data that does not exist, rather than trading on
a fabricated tilt.

Packages affected (they run, but the smart-money gate never passes): `badger`,
and any other package whose scanner calls `leaderboard_get_markets` or
`market_get_cross_asset_flows`. Verified by
`tests/aftermath_runtime/test_strategy_runnability.py`, which runs all 125
scanner instances against both adapters and asserts none crash.

### `strategy_get_clearinghouse_state` — what "degraded" means precisely

The upstream payload has `main` and `xyz` sections because Hyperliquid exposes
two views of one **cross-margined** wallet. Aftermath has neither a builder dex
nor cross margin, so only `main` is emitted. Scanners that `max()` across the two
sections keep working unchanged.

Two fields are derived, with the policy stated rather than left implicit:

- `totalMarginUsed` = sum of per-position **isolated** collateral.
- `totalNtlPos` = sum of **absolute** position notional.

Neither is the upstream cross-margin aggregate. Relabelling isolated collateral
as a cross-margin figure is how a port silently mis-sizes, so the difference is
recorded in the payload's own `notes` field and in `marginModel: "isolated"`.

`oi_velocity` is omitted from `market_get_asset_data`: no Aftermath route serves
it. The upstream scanners already fall back to computing an OI baseline
themselves, which is why they still run.

## Analysis / lifecycle surface

| tool | status | backed by |
|---|---|---|
| `market_get_prices` | implemented | `markets/prices` |
| `strategy_get_asset_trading_limits` | implemented | `all-markets` marketParams + `account/max-order-size` |
| `execution_get_closed_position_details` | implemented | `account/order-history-detailed` |
| `strategy_get_pnl_and_account_value_history` | implemented | `account/collateral-history` + `account/margin-history` |
| `account_get_portfolio` | degraded | `accounts/owned` + `accounts/positions` |
| `strategy_list` | degraded | `accounts/owned` |
| `strategy_get` | degraded | `accounts` + `accounts/positions` |
| `user_get_referral_rewards` | degraded | `referrals/*` + `rewards/claimable` |
| `user_get_senpi_points` | degraded | `rewards/points` |
| `user_get_me` | **unavailable** | — |
| `leaderboard_get_trader_positions` | **unavailable** | — |
| `leaderboard_get_momentum_events` | **unavailable** | — |
| `leaderboard_get_status` | **unavailable** | — |
| `discovery_get_top_traders` | **unavailable** | — |
| `discovery_get_trader_state` | **unavailable** | — |
| `discovery_get_trader_history` | **unavailable** | — |
| `discovery_get_top_strategies` | **unavailable** | — |

`account_get_portfolio` omits wallet-level idle balances: **the entire
`/api/wallet/*` family is published in the spec but returns 404 on the live host**
(verified 2026-07-28). The adapter reports that as a `gaps` entry in the payload
rather than guessing a balance, and `doctor` degrades rather than failing.

`user_get_senpi_points` needs a signed challenge — v3.0.0 made
`/api/rewards/points` require `bytes` + `signature`, and renamed the response
from `{points}` (int) to `{totalPoints}` (float). This runtime never signs, so
the caller must supply the challenge or the call raises.

## Mutations (build-only, disabled by default)

| tool | route |
|---|---|
| `strategy_create_custom_strategy` | composed onboarding PTB (`create-account` + deposit + allocate) |
| `strategy_create` | `transactions/create-account` |
| `strategy_top_up` | `account/transactions/deposit-collateral` (serialised) |
| `strategy_withdraw_funds` | `account/transactions/withdraw-collateral` (serialised) |
| `strategy_open` | `account/transactions/place-market-order` |
| `strategy_close_positions` | `account/transactions/place-market-order` (reduceOnly) |
| `strategy_pause` | `account/transactions/cancel-orders` |
| `strategy_update` | `account/transactions/set-leverage` |
| `strategy_close` | **refused** — a multi-transaction teardown; see `ATOMICITY.md` |

With `AF_ARMED` unset, every one of these raises before any request is made.
Even armed, they stop at an inspected transaction: nothing is signed, and no
submit route exists in any transport allowlist.
