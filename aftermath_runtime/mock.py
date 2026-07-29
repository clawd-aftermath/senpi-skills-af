"""Interface-identical mock adapter.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

Every strategy must be runnable with **zero network and zero keys**.  This is
that path: ``MockAftermathAdapter`` answers the same tool surface as
``AftermathAdapter`` from deterministic in-memory data.

Interface parity is enforced by a test, not by discipline
(``tests/aftermath_runtime/test_adapter.py``).  If a handler is added to one
and not the other, the suite fails.

The mock is deliberately NOT a stub that returns empty payloads.  It serves
plausibly-shaped data so that a strategy exercised against it actually runs its
scoring path, and it raises the same ``CapabilityUnavailable`` for the same
tools, so a strategy that would fail a gate in production also fails it here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .config import DEFAULT_COLLATERAL_COIN_TYPE, RuntimeConfig
from .errors import CapabilityUnavailable, WriteDenied
from .gas import GasConfig
from .safety import BotState, CircuitBreaker, KillSwitch
from .toolspec import BUILD_ONLY, TOOL_NAMES, TOOLS_BY_NAME, UNAVAILABLE

MOCK_WALLET = "0x" + "ab" * 32
_MOCK_MARKET_ID = "0x" + "11" * 32


@dataclass
class MockMarket:
    symbol: str
    market_id: str
    index_price: float
    open_interest: float = 1_000.0
    max_leverage: float = 10.0
    funding_rate: float = 0.0001
    funding_frequency_ms: int = 3_600_000
    min_order_usd_value: float = 10.0
    lot_size_native: int = 1_000
    tick_size_native: int = 1_000
    margin_ratio_initial: float = 0.1
    margin_ratio_maintenance: float = 0.05


DEFAULT_MOCK_MARKETS: tuple[MockMarket, ...] = (
    MockMarket("BTC", _MOCK_MARKET_ID, 65_000.0),
    MockMarket("ETH", "0x" + "22" * 32, 3_200.0),
    MockMarket("SOL", "0x" + "33" * 32, 150.0),
)


@dataclass
class MockAftermathAdapter:
    """A network-free, key-free twin of :class:`AftermathAdapter`."""

    config: RuntimeConfig = field(
        default_factory=lambda: RuntimeConfig(
            wallet_address=MOCK_WALLET,
            collateral_coin_type=DEFAULT_COLLATERAL_COIN_TYPE,
            account_id=1,
        )
    )
    markets: Sequence[MockMarket] = DEFAULT_MOCK_MARKETS
    account_value: float = 10_000.0
    withdrawable: float = 8_000.0
    positions: Sequence[Mapping[str, Any]] = ()
    open_orders: Sequence[Mapping[str, Any]] = ()
    clock: Callable[[], float] = field(default=time.time, repr=False)
    log: Callable[[str], None] = field(default=lambda message: None, repr=False)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)

    def __post_init__(self) -> None:
        self.gas = GasConfig(
            mode=self.config.gas_mode,
            budget_mist=self.config.gas_budget_mist,
            gas_coin_type=self.config.gas_coin_type,
        )
        self.kill_switch = KillSwitch(
            max_silence_seconds=120.0,
            cancel_all=self._cancel_all_and_verify,
            log=self.log,
        )

    # ── Parity surface ───────────────────────────────────────────

    @property
    def tool_names(self) -> tuple[str, ...]:
        return TOOL_NAMES

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> Any:
        args = dict(arguments or {})
        self.calls.append((name, args))
        spec = TOOLS_BY_NAME.get(name)
        if spec is None:
            raise CapabilityUnavailable(name, "unknown tool")
        if spec.status == UNAVAILABLE:
            raise CapabilityUnavailable(name, spec.note or spec.backing)
        if spec.status == BUILD_ONLY:
            self.circuit_breaker.assert_can_trade()
            if not self.config.armed:
                raise WriteDenied(
                    f"refusing to build {name}: the mock runtime is not armed"
                )
            return {
                "success": True,
                "venue": "aftermath",
                "submitted": False,
                "data": {
                    "txKind": "bW9jaw==",
                    "intent": name,
                    "gasMode": self.gas.mode,
                    "inspected": True,
                    "deferred": None,
                    "note": "mock adapter: nothing is built, signed or sent",
                },
            }
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:  # pragma: no cover - guarded by the parity test
            raise CapabilityUnavailable(name, "no handler bound")
        return handler(args)

    def observe(self, state: BotState) -> list[str]:
        self.kill_switch.heartbeat()
        return self.circuit_breaker.evaluate(state)

    def _cancel_all_and_verify(self) -> list[Mapping[str, Any]]:
        self.open_orders = ()
        return list(self.open_orders)

    # ── Helpers ──────────────────────────────────────────────────

    def _market(self, name: str) -> MockMarket:
        from .ids import normalise_instrument

        query = normalise_instrument(str(name))
        for market in self.markets:
            if market.symbol == query or market.market_id == str(name):
                return market
        from .errors import MarketUnavailable

        raise MarketUnavailable(f"no mock Aftermath market for {name!r}")

    # ── Handlers ─────────────────────────────────────────────────

    def _tool_market_list_instruments(self, args: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                "instruments": [
                    {
                        "symbol": m.symbol,
                        "marketId": m.market_id,
                        "collateralCoinType": self.config.collateral_coin_type,
                        "maxLeverage": m.max_leverage,
                        "lotSize": f"{m.lot_size_native}n",
                        "tickSize": f"{m.tick_size_native}n",
                        "minOrderUsdValue": m.min_order_usd_value,
                        "makerFee": 0.0002,
                        "takerFee": 0.0005,
                        "priorityTakerFee": None,
                        "isDelisted": False,
                    }
                    for m in self.markets
                ],
                "count": len(self.markets),
            },
            "warnings": [],
        }

    def _tool_market_get_prices(self, args: Mapping[str, Any]) -> dict[str, Any]:
        requested = args.get("assets") or [m.symbol for m in self.markets]
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                self._market(a).symbol: {
                    "markPrice": self._market(a).index_price,
                    "indexPrice": self._market(a).index_price,
                    "midPrice": self._market(a).index_price,
                    "marketId": self._market(a).market_id,
                }
                for a in requested
            },
        }

    def _tool_market_get_asset_data(self, args: Mapping[str, Any]) -> dict[str, Any]:
        market = self._market(args.get("asset") or args.get("coin") or "")
        data: dict[str, Any] = {
            "marketId": market.market_id,
            "symbol": market.symbol,
            "asset_context": {
                "openInterest": market.open_interest,
                "markPx": market.index_price,
                "oraclePx": market.index_price,
                "midPx": market.index_price,
                "dayNtlVlm": 1_000_000.0,
                "prevDayPx": None,
                "priceChangePercentage": 0.0,
                "maxLeverage": market.max_leverage,
                "funding": market.funding_rate,
                "nextFundingTimestampMs": int(self.clock() * 1000) + 3_600_000,
            },
            "market_params": {
                "marginRatioInitial": market.margin_ratio_initial,
                "marginRatioMaintenance": market.margin_ratio_maintenance,
                "minOrderUsdValue": market.min_order_usd_value,
                "makerFee": 0.0002,
                "takerFee": 0.0005,
            },
        }
        intervals = args.get("candle_intervals") or args.get("intervals") or []
        if intervals:
            now_ms = int(self.clock() * 1000)
            data["candles"] = {
                str(interval): [
                    {
                        "t": now_ms - (n * 3_600_000),
                        "o": str(market.index_price),
                        "h": str(market.index_price * 1.01),
                        "l": str(market.index_price * 0.99),
                        "c": str(market.index_price),
                        "v": "100.0",
                    }
                    for n in range(24, 0, -1)
                ]
                for interval in intervals
            }
        if args.get("include_funding"):
            data["funding_history"] = []
        if args.get("include_order_book"):
            data["order_book"] = None
        return {"success": True, "venue": "aftermath", "data": data}

    def _tool_market_get_funding_history(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        market = self._market(args.get("asset") or args.get("coin") or "")
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                "marketId": market.market_id,
                "symbol": market.symbol,
                "fundingIntervalMs": market.funding_frequency_ms,
                "history": [],
            },
        }

    def _tool_market_get_funding_regime(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                m.symbol: {
                    "marketId": m.market_id,
                    "fundingRate": m.funding_rate,
                    "fundingAnnualizedPct": m.funding_rate
                    * ((365 * 86_400_000) / m.funding_frequency_ms)
                    * 100.0,
                    "fundingIntervalMs": m.funding_frequency_ms,
                    "regime": "neutral",
                }
                for m in self.markets
            },
        }

    def _tool_strategy_get_clearinghouse_state(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                "main": {
                    "marginSummary": {
                        "accountValue": str(self.account_value),
                        "totalMarginUsed": str(
                            sum(float(p.get("marginUsed", 0)) for p in self.positions)
                        ),
                        "totalNtlPos": str(
                            sum(abs(float(p.get("notional", 0))) for p in self.positions)
                        ),
                        "totalRawUsd": str(self.account_value),
                    },
                    "withdrawable": str(self.withdrawable),
                    "assetPositions": [{"position": dict(p)} for p in self.positions],
                },
                "accountId": f"{self.config.account_id or 1}n",
                "marginModel": "isolated",
                "notes": ["mock adapter"],
            },
        }

    def _tool_strategy_get_open_orders(self, args: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "venue": "aftermath",
            "data": {"orders": list(self.open_orders), "count": len(self.open_orders)},
        }

    def _tool_strategy_get_asset_trading_limits(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        market = self._market(args.get("asset") or args.get("coin") or "")
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                "marketId": market.market_id,
                "symbol": market.symbol,
                "maxLeverage": market.max_leverage,
                "minOrderUsdValue": market.min_order_usd_value,
                "lotSize": f"{market.lot_size_native}n",
                "tickSize": f"{market.tick_size_native}n",
                "maxPendingOrders": 100,
                "marginRatioInitial": market.margin_ratio_initial,
                "marginRatioMaintenance": market.margin_ratio_maintenance,
            },
        }

    def _tool_audit_query(self, args: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "venue": "aftermath",
            "data": {"events": [], "count": 0, "nextCursor": None},
        }

    def _tool_execution_get_closed_position_details(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {"success": True, "venue": "aftermath", "data": {"orders": []}}

    def _tool_strategy_get_pnl_and_account_value_history(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "success": True,
            "venue": "aftermath",
            "data": {"collateralHistory": [], "marginHistory": []},
        }

    def _tool_account_get_portfolio(self, args: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                "accounts": [
                    {
                        "accountId": f"{self.config.account_id or 1}n",
                        "accountCapId": "0x" + "cc" * 32,
                        "collateralCoinType": self.config.collateral_coin_type,
                        "totalEquityUsd": self.account_value,
                        "availableCollateralUsd": self.withdrawable,
                        "unrealizedPnlUsd": 0.0,
                        "positionCount": len(self.positions),
                    }
                ],
                "walletBalances": None,
                "gaps": ["mock adapter: wallet balances are not modelled"],
            },
        }

    def _tool_strategy_list(self, args: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                "strategies": [
                    {
                        "accountId": f"{self.config.account_id or 1}n",
                        "accountCapId": "0x" + "cc" * 32,
                        "collateralCoinType": self.config.collateral_coin_type,
                        "collateral": self.account_value,
                        "isAgent": False,
                    }
                ],
                "note": "mock adapter",
            },
        }

    def _tool_strategy_get(self, args: Mapping[str, Any]) -> dict[str, Any]:
        return self._tool_strategy_get_clearinghouse_state(args)

    def _tool_user_get_referral_rewards(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        raise CapabilityUnavailable(
            "user_get_referral_rewards", "needs a signed challenge"
        )

    def _tool_user_get_senpi_points(self, args: Mapping[str, Any]) -> dict[str, Any]:
        raise CapabilityUnavailable(
            "user_get_senpi_points", "needs a signed challenge (bytes + signature)"
        )
