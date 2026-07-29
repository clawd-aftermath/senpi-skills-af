"""The complete upstream MCP tool surface, and what Aftermath can do about it.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

This is the interface contract every strategy package already calls.  The
adapter implements it; the mock adapter mirrors it; a test enforces that the
two agree.  Nothing here is aspirational — each entry records exactly which
Aftermath V2 route backs it, or why nothing can.

Statuses
--------
``implemented``   fully served from Aftermath V2 routes.
``degraded``      served, but a documented part of the upstream payload has no
                  Aftermath equivalent and is omitted rather than faked.
``build_only``    a mutation; the adapter builds, previews and inspects a
                  transaction and stops before signing.  Disabled unless armed.
``unavailable``   Aftermath genuinely has no such data.  Raises
                  ``CapabilityUnavailable``.  It never returns a plausible
                  substitute — a fabricated number is worse than an error.

The nine tools the strategy packages actually invoke through
``ctx.senpi_mcp.call_tool`` are marked ``strategy_critical``.  They were found
by parsing every ``strategies/**/*.py``; the rest of the surface belongs to the
lifecycle/analysis skills.
"""

from __future__ import annotations

from dataclasses import dataclass

IMPLEMENTED = "implemented"
DEGRADED = "degraded"
BUILD_ONLY = "build_only"
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    status: str
    backing: str
    note: str = ""
    strategy_critical: bool = False


TOOL_SPECS: tuple[ToolSpec, ...] = (
    # ── Called directly by strategy packages ─────────────────────
    ToolSpec(
        "market_get_asset_data",
        IMPLEMENTED,
        "/api/perpetuals/all-markets + /api/perpetuals/markets/prices + "
        "/api/perpetuals/markets/24hr-stats + /api/perpetuals/market/candle-history "
        "+ /api/perpetuals/markets/orderbooks",
        "asset_context.openInterest comes from marketState.openInterest; "
        "funding from estimatedFundingRate. oi_velocity is not served by any "
        "Aftermath route and is omitted so callers fall back to their own "
        "baseline computation.",
        strategy_critical=True,
    ),
    ToolSpec(
        "strategy_get_clearinghouse_state",
        DEGRADED,
        "/api/perpetuals/accounts/owned + /api/perpetuals/accounts/positions",
        "Emitted under the single 'main' section only. There is no second "
        "builder-dex view to collapse, and totalMarginUsed/totalNtlPos are "
        "derived from isolated per-position collateral and notional with the "
        "policy stated in the adapter — they are not the upstream cross-margin "
        "aggregates.",
        strategy_critical=True,
    ),
    ToolSpec(
        "leaderboard_get_markets",
        UNAVAILABLE,
        "-",
        "Upstream this is a smart-money positioning feed (per-asset long/short "
        "tilt across ranked traders). Aftermath exposes no cross-account trader "
        "positioning data at all. Strategies gating on it will fail that gate "
        "and skip, which is the correct behaviour.",
        strategy_critical=True,
    ),
    ToolSpec(
        "market_list_instruments",
        IMPLEMENTED,
        "/api/perpetuals/all-markets",
        "maxLeverage is derived as 1/marginRatioInitial; Aftermath has no "
        "leverage field. Instruments are Aftermath marketIds, never tickers.",
        strategy_critical=True,
    ),
    ToolSpec(
        "market_get_funding_regime",
        IMPLEMENTED,
        "/api/perpetuals/all-markets + /api/perpetuals/market/funding-history",
        "Regime is classified from the API's own estimatedFundingRate and the "
        "long/short funding history; the thresholds are the adapter's and are "
        "documented in code.",
        strategy_critical=True,
    ),
    ToolSpec(
        "market_get_funding_history",
        IMPLEMENTED,
        "/api/perpetuals/market/funding-history",
        "",
        strategy_critical=True,
    ),
    ToolSpec(
        "market_get_cross_asset_flows",
        UNAVAILABLE,
        "-",
        "Cross-asset capital rotation is computed upstream from trader-level "
        "flow data Aftermath does not publish.",
        strategy_critical=True,
    ),
    ToolSpec(
        "strategy_get_open_orders",
        IMPLEMENTED,
        "/api/ccxt/myPendingOrders",
        "Reads use accountNumber (a plain number) and chId (the marketId); the "
        "CCXT WRITE surface uses the capability object id instead. The adapter "
        "types the three separately.",
        strategy_critical=True,
    ),
    ToolSpec(
        "audit_query",
        IMPLEMENTED,
        "/api/perpetuals/account/order-history",
        "Paginated with beforeTimestampCursor / nextBeforeTimestampCursor.",
        strategy_critical=True,
    ),
    # ── Market / data surface used by the analysis skills ────────
    ToolSpec(
        "market_get_prices",
        IMPLEMENTED,
        "/api/perpetuals/markets/prices",
        "",
    ),
    ToolSpec(
        "strategy_get_asset_trading_limits",
        IMPLEMENTED,
        "/api/perpetuals/all-markets + /api/perpetuals/account/max-order-size",
        "minOrderUsdValue, lot/tick, maxPendingOrders and derived max leverage "
        "come from marketParams; the account-aware ceiling comes from "
        "max-order-size.",
    ),
    ToolSpec(
        "account_get_portfolio",
        DEGRADED,
        "/api/perpetuals/accounts/owned + /api/perpetuals/accounts/positions",
        "Wallet-level idle balances are omitted: the whole /api/wallet/* family "
        "is in the spec but 404s live as of 2026-07-28. The adapter reports the "
        "gap in the payload instead of guessing a balance.",
    ),
    ToolSpec(
        "execution_get_closed_position_details",
        IMPLEMENTED,
        "/api/perpetuals/account/order-history-detailed",
        "",
    ),
    ToolSpec(
        "strategy_get_pnl_and_account_value_history",
        IMPLEMENTED,
        "/api/perpetuals/account/collateral-history + "
        "/api/perpetuals/account/margin-history",
        "",
    ),
    # ── Mutations: built, previewed, inspected, never signed ─────
    ToolSpec(
        "strategy_create_custom_strategy",
        BUILD_ONLY,
        "/api/perpetuals/transactions/create-account (+ deposit + allocate, "
        "composed as ONE PTB)",
        "Upstream this provisions a funded wallet. Here it is the composed "
        "onboarding PTB. Disabled unless armed.",
    ),
    ToolSpec(
        "strategy_create",
        BUILD_ONLY,
        "/api/perpetuals/transactions/create-account",
        "Copy-trader creation has no Aftermath analogue; only the account "
        "provisioning half is served.",
    ),
    ToolSpec(
        "strategy_top_up",
        BUILD_ONLY,
        "/api/perpetuals/account/transactions/deposit-collateral",
        "Deposits are serialised through a single gate: parallel deposits race "
        "on Sui coin-object versions.",
    ),
    ToolSpec(
        "strategy_withdraw_funds",
        BUILD_ONLY,
        "/api/perpetuals/account/transactions/withdraw-collateral",
        "",
    ),
    ToolSpec(
        "strategy_close_positions",
        BUILD_ONLY,
        "/api/perpetuals/account/transactions/place-market-order (reduceOnly)",
        "",
    ),
    ToolSpec(
        "strategy_close",
        BUILD_ONLY,
        "/api/perpetuals/account/transactions/cancel-orders + "
        "place-market-order (reduceOnly) + withdraw-collateral",
        "Still SEVERAL transactions: closing must observe the resulting fill "
        "before the withdrawable amount is known. Forcing atomicity here would "
        "change the semantics.",
    ),
    ToolSpec(
        "strategy_update",
        BUILD_ONLY,
        "/api/perpetuals/account/transactions/set-leverage",
        "",
    ),
    ToolSpec(
        "strategy_pause",
        BUILD_ONLY,
        "/api/perpetuals/account/transactions/cancel-orders",
        "Pausing cancels resting quotes in ONE transaction across markets.",
    ),
    ToolSpec(
        "strategy_open",
        BUILD_ONLY,
        "/api/perpetuals/account/transactions/place-market-order",
        "",
    ),
    ToolSpec(
        "strategy_list",
        DEGRADED,
        "/api/perpetuals/accounts/owned",
        "Aftermath has accounts, not named Senpi strategies. Each owned account "
        "is reported as one entry; upstream strategy metadata (name, skill "
        "attribution, DSL) lives in the Senpi control plane, not on-chain.",
    ),
    ToolSpec(
        "strategy_get",
        DEGRADED,
        "/api/perpetuals/accounts + /api/perpetuals/accounts/positions",
        "Same limitation as strategy_list.",
    ),
    # ── Genuinely unavailable ────────────────────────────────────
    ToolSpec(
        "leaderboard_get_trader_positions",
        UNAVAILABLE,
        "-",
        "No cross-account trader data on Aftermath.",
    ),
    ToolSpec(
        "leaderboard_get_momentum_events",
        UNAVAILABLE,
        "-",
        "No cross-account trader data on Aftermath.",
    ),
    ToolSpec(
        "leaderboard_get_status",
        UNAVAILABLE,
        "-",
        "No leaderboard exists.",
    ),
    ToolSpec(
        "discovery_get_top_traders",
        UNAVAILABLE,
        "-",
        "Trader discovery is a Senpi data product, not a venue capability.",
    ),
    ToolSpec(
        "discovery_get_trader_state",
        UNAVAILABLE,
        "-",
        "Requires reading another wallet's positions; Aftermath exposes "
        "positions only for account ids, and discovering another trader's "
        "account id from a wallet is not a supported query.",
    ),
    ToolSpec(
        "discovery_get_trader_history",
        UNAVAILABLE,
        "-",
        "Same as discovery_get_trader_state.",
    ),
    ToolSpec(
        "discovery_get_top_strategies",
        UNAVAILABLE,
        "-",
        "Senpi control-plane data.",
    ),
    ToolSpec(
        "user_get_me",
        UNAVAILABLE,
        "-",
        "There is no Senpi user on Aftermath. The operator is a wallet address.",
    ),
    ToolSpec(
        "user_get_referral_rewards",
        DEGRADED,
        "/api/referrals/query + /api/rewards/claimable",
        "Aftermath referrals are a different scheme with different fields; the "
        "adapter surfaces the Aftermath shape and does not pretend it is the "
        "Senpi one.",
    ),
    ToolSpec(
        "user_get_senpi_points",
        DEGRADED,
        "/api/rewards/points",
        "Aftermath points, not Senpi points. v3.0.0 renamed the response from "
        "{points} (int) to {totalPoints} (float) and the route now requires "
        "bytes + signature, so it needs a signed challenge the operator must "
        "supply.",
    ),
)

TOOL_NAMES: tuple[str, ...] = tuple(spec.name for spec in TOOL_SPECS)
TOOLS_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in TOOL_SPECS}

STRATEGY_CRITICAL_TOOLS: tuple[str, ...] = tuple(
    spec.name for spec in TOOL_SPECS if spec.strategy_critical
)


def coverage_summary() -> dict[str, int]:
    summary: dict[str, int] = {}
    for spec in TOOL_SPECS:
        summary[spec.status] = summary.get(spec.status, 0) + 1
    return summary


def coverage_table() -> str:
    """A printable coverage table.  Used by ``doctor`` and by the README."""
    width = max(len(spec.name) for spec in TOOL_SPECS)
    lines = [f"{'tool'.ljust(width)}  status        backing"]
    lines.append("-" * (width + 60))
    for spec in TOOL_SPECS:
        mark = "*" if spec.strategy_critical else " "
        lines.append(
            f"{spec.name.ljust(width)}{mark} {spec.status.ljust(12)}  {spec.backing}"
        )
    lines.append("")
    lines.append("* = invoked directly by a strategy package's scanner")
    return "\n".join(lines)
