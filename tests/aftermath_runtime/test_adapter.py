"""The one adapter: tool coverage, parity with the mock, venue removal.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aftermath_runtime.adapter import AftermathAdapter  # noqa: E402
from aftermath_runtime.config import RuntimeConfig  # noqa: E402
from aftermath_runtime.errors import (  # noqa: E402
    CapabilityUnavailable,
    MarketUnavailable,
    WriteDenied,
)
from aftermath_runtime.mock import MockAftermathAdapter  # noqa: E402
from aftermath_runtime.toolspec import (  # noqa: E402
    BUILD_ONLY,
    STRATEGY_CRITICAL_TOOLS,
    TOOL_NAMES,
    TOOL_SPECS,
    UNAVAILABLE,
    coverage_summary,
    coverage_table,
)
from aftermath_runtime.transport import AdapterFixtureTransport  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WALLET = "0x" + "ab" * 32
BTC = "0x1111111111111111111111111111111111111111111111111111111111111111"
ETH = "0x2222222222222222222222222222222222222222222222222222222222222222"
COLLATERAL = "0xusdc::usdc::USDC"
TX_KIND = "dHhraW5k"
# Sponsored gas is the default, so a builder response must echo a sponsor
# signature or inspection rightly refuses it.
SPONSORED_TX = {"txKind": TX_KIND, "sponsorSignature": "c2ln"}


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def responses(**overrides):
    base = {
        "/api/perpetuals/all-markets": fixture("all_markets.json"),
        "/api/perpetuals/accounts/owned": {
            "accountCaps": [
                {
                    "accountId": 7,
                    "objectId": "0x" + "cc" * 32,
                    "accountObjectId": "0x" + "dd" * 32,
                    "accountObjectInitialSharedVersion": 1,
                    "collateral": 1000.0,
                    "collateralCoinType": COLLATERAL,
                    "isAgent": False,
                    "objectDigest": "digest",
                    "objectVersion": 1,
                    "walletAddress": WALLET,
                    "whitelistedAgentCapIds": [],
                }
            ]
        },
        "/api/perpetuals/accounts/positions": {
            "accounts": [
                {
                    "accountId": 7,
                    "availableCollateral": 900,
                    "availableCollateralUsd": 899.5,
                    "totalEquityUsd": 1007.5,
                    "totalUnrealizedFundingsUsd": -0.05,
                    "totalUnrealizedPnlUsd": 8,
                    "positions": [
                        {
                            "marketId": BTC,
                            "baseAssetAmount": 0.01,
                            "collateral": 100,
                            "collateralUsd": 99.95,
                            "quoteAssetNotionalAmount": 638,
                            "entryPrice": 63000,
                            "liquidationPrice": 45000,
                            "leverage": 3,
                            "marginRatio": 0.15,
                            "unrealizedPnlUsd": 8,
                            "pendingOrders": [],
                        }
                    ],
                }
            ]
        },
        "/api/perpetuals/markets/prices": {
            "marketsPrices": [
                {
                    "marketId": BTC,
                    "basePrice": 63500.0,
                    "collateralPrice": 1.0,
                    "markPrice": 63510.0,
                    "midPrice": 63505.0,
                },
                {
                    "marketId": ETH,
                    "basePrice": 3200.0,
                    "collateralPrice": 1.0,
                    "markPrice": 3201.0,
                    "midPrice": 3200.5,
                },
            ]
        },
        "/api/perpetuals/markets/24hr-stats": {
            "marketsStats": [
                {
                    "basePrice": 63500.0,
                    "collateralPrice": 1.0,
                    "markPrice": 63510.0,
                    "midPrice": 63505.0,
                    "priceChange": 500.0,
                    "priceChangePercentage": 0.8,
                    "volumeBaseAssetAmount": 12.0,
                    "volumeUsd": 760_000.0,
                }
            ]
        },
        "/api/perpetuals/market/candle-history": {
            "candles": [
                {
                    "timestamp": 1789990000000,
                    "open": 63000.0,
                    "high": 63600.0,
                    "low": 62900.0,
                    "close": 63500.0,
                    "volume": 10.5,
                }
            ]
        },
        "/api/perpetuals/market/funding-history": {"history": []},
        "/api/ccxt/myPendingOrders": [],
        "/api/perpetuals/account/order-history": {
            "orders": [{"eventType": "fill", "marketId": BTC}],
            "nextBeforeTimestampCursor": None,
        },
        # POST, and it requires {walletAddress} -- not a GET, not a ping.
        "/api/gas-pool/pool": {
            "balance": 1_000_000_000,
            "gasPoolId": "0x" + "ee" * 32,
            "walletAddress": "0x" + "fe" * 32,
            "whitelistedAddresses": [WALLET],
        },
    }
    base.update(overrides)
    return base


def adapter(armed: bool = False, **overrides) -> AftermathAdapter:
    transport = AdapterFixtureTransport(responses(**overrides))
    config = RuntimeConfig(
        wallet_address=WALLET, collateral_coin_type=COLLATERAL, armed=armed
    )
    instance = AftermathAdapter(transport, config)
    instance._test_transport = transport  # type: ignore[attr-defined]
    return instance


class InterfaceParityTests(unittest.TestCase):
    """The mock twin must stay in lockstep, enforced here rather than by hand."""

    def test_both_adapters_expose_the_same_tool_names(self):
        self.assertEqual(
            AftermathAdapter(AdapterFixtureTransport({}), RuntimeConfig()).tool_names,
            MockAftermathAdapter().tool_names,
        )

    def test_every_servable_tool_has_a_handler_on_both_adapters(self):
        real = AftermathAdapter(AdapterFixtureTransport({}), RuntimeConfig())
        mock = MockAftermathAdapter()
        missing_real, missing_mock = [], []
        for spec in TOOL_SPECS:
            if spec.status == UNAVAILABLE:
                continue
            if not hasattr(real, f"_tool_{spec.name}") and spec.status != BUILD_ONLY:
                missing_real.append(spec.name)
            if spec.status == BUILD_ONLY:
                # The mock serves build-only tools generically.
                if not hasattr(real, f"_tool_{spec.name}"):
                    missing_real.append(spec.name)
                continue
            if not hasattr(mock, f"_tool_{spec.name}"):
                missing_mock.append(spec.name)
        self.assertEqual(missing_real, [], "real adapter is missing handlers")
        self.assertEqual(missing_mock, [], "mock adapter is missing handlers")

    def test_unavailable_tools_are_unavailable_on_BOTH(self):
        real = AftermathAdapter(AdapterFixtureTransport({}), RuntimeConfig())
        mock = MockAftermathAdapter()
        for spec in TOOL_SPECS:
            if spec.status != UNAVAILABLE:
                continue
            with self.subTest(tool=spec.name):
                with self.assertRaises(CapabilityUnavailable):
                    real.call_tool(spec.name)
                with self.assertRaises(CapabilityUnavailable):
                    mock.call_tool(spec.name)

    def test_an_unknown_tool_raises_rather_than_returning_empty(self):
        for instance in (
            AftermathAdapter(AdapterFixtureTransport({}), RuntimeConfig()),
            MockAftermathAdapter(),
        ):
            with self.assertRaises(CapabilityUnavailable):
                instance.call_tool("market_get_nonexistent")

    def test_the_nine_strategy_critical_tools_are_all_declared(self):
        # These are the tools parsed out of strategies/**/*.py.
        self.assertEqual(
            set(STRATEGY_CRITICAL_TOOLS),
            {
                "market_get_asset_data",
                "strategy_get_clearinghouse_state",
                "leaderboard_get_markets",
                "market_list_instruments",
                "market_get_cross_asset_flows",
                "strategy_get_open_orders",
                "audit_query",
                "market_get_funding_regime",
                "market_get_funding_history",
            },
        )

    def test_coverage_summary_accounts_for_every_tool(self):
        self.assertEqual(sum(coverage_summary().values()), len(TOOL_NAMES))
        self.assertIn("market_get_asset_data", coverage_table())


class MarketResolutionTests(unittest.TestCase):
    def test_all_markets_is_posted_with_the_collateral_coin_type(self):
        instance = adapter()
        instance.refresh_markets()
        path, body = instance._test_transport.calls[0]
        self.assertEqual(path, "/api/perpetuals/all-markets")
        self.assertEqual(body, {"collateralCoinType": COLLATERAL})

    def test_markets_are_objects_not_a_bare_array(self):
        instance = adapter(**{"/api/perpetuals/all-markets": []})
        with self.assertRaisesRegex(Exception, "object"):
            instance.refresh_markets()

    def test_zero_markets_warns_and_never_raises(self):
        logs: list[str] = []
        transport = AdapterFixtureTransport(
            responses(**{"/api/perpetuals/all-markets": {"markets": []}})
        )
        instance = AftermathAdapter(
            transport,
            RuntimeConfig(wallet_address=WALLET, collateral_coin_type=COLLATERAL),
            log=logs.append,
        )
        catalog = instance.refresh_markets()
        self.assertTrue(catalog.is_empty)
        self.assertTrue(any("no Aftermath perpetual markets" in m for m in logs))
        result = instance.call_tool("market_list_instruments")
        self.assertEqual(result["data"]["count"], 0)
        self.assertTrue(result["warnings"])

    def test_resolving_against_an_empty_universe_still_raises(self):
        instance = adapter(**{"/api/perpetuals/all-markets": {"markets": []}})
        with self.assertRaisesRegex(MarketUnavailable, "expected before the relaunch"):
            instance.resolve_market("BTC")

    def test_a_ticker_resolves_to_an_api_issued_market_id(self):
        instance = adapter()
        self.assertEqual(str(instance.resolve_market("BTC").market_id), BTC)
        # The marketId is NOT the ticker.
        self.assertNotEqual(str(instance.resolve_market("BTC").market_id), "BTC")

    def test_a_hip3_prefixed_symbol_is_stripped_not_repointed(self):
        instance = adapter()
        self.assertEqual(str(instance.resolve_market("xyz:BTC").market_id), BTC)
        self.assertEqual(str(instance.resolve_market("BTC-PERP").market_id), BTC)

    def test_max_leverage_is_derived_from_the_margin_ratio(self):
        instance = adapter()
        self.assertAlmostEqual(instance.resolve_market("BTC").max_leverage, 10.0)
        self.assertAlmostEqual(instance.resolve_market("ETH").max_leverage, 20.0)

    def test_a_pre_v3_market_params_payload_is_rejected(self):
        payload = fixture("all_markets.json")
        payload["markets"][0]["marketParams"]["gasPriceTakerFee"] = 0.001
        instance = adapter(**{"/api/perpetuals/all-markets": payload})
        with self.assertRaisesRegex(Exception, "removed in v3.0.0"):
            instance.refresh_markets()


class AccountDiscoveryTests(unittest.TestCase):
    def test_the_wallet_is_the_only_required_input(self):
        instance = adapter()
        cap = instance.account()
        self.assertEqual(cap.account_id.value, 7)
        self.assertEqual(str(cap.cap_object_id), "0x" + "cc" * 32)
        path, body = instance._test_transport.calls[0]
        self.assertEqual(path, "/api/perpetuals/accounts/owned")
        self.assertEqual(body, {"walletAddress": WALLET})

    def test_owned_accounts_must_be_an_object_with_accountCaps(self):
        instance = adapter(**{"/api/perpetuals/accounts/owned": []})
        with self.assertRaisesRegex(Exception, "accountCaps"):
            instance.owned_accounts()

    def test_a_missing_wallet_is_an_actionable_error_and_never_a_key(self):
        instance = AftermathAdapter(AdapterFixtureTransport({}), RuntimeConfig())
        with self.assertRaisesRegex(Exception, "AF_WALLET_ADDRESS"):
            instance.require_wallet()


class ToolBehaviourTests(unittest.TestCase):
    def test_clearinghouse_state_keeps_the_upstream_envelope(self):
        result = adapter().call_tool(
            "strategy_get_clearinghouse_state", {"strategy_wallet": WALLET}
        )
        data = result["data"]
        # Scanners read data["main"]["marginSummary"]["accountValue"] and
        # iterate assetPositions -- that shape is preserved verbatim.
        self.assertEqual(data["main"]["marginSummary"]["accountValue"], "1007.5")
        self.assertEqual(data["main"]["withdrawable"], "899.5")
        position = data["main"]["assetPositions"][0]["position"]
        self.assertEqual(position["coin"], "BTC")
        self.assertEqual(position["szi"], "0.01")
        self.assertEqual(position["leverage"]["type"], "isolated")
        # ...and the Hyperliquid builder-dex section is GONE, not re-pointed.
        self.assertNotIn("xyz", data)
        self.assertEqual(data["marginModel"], "isolated")

    def test_isolated_aggregates_are_derived_with_a_stated_policy(self):
        data = adapter().call_tool("strategy_get_clearinghouse_state")["data"]
        summary = data["main"]["marginSummary"]
        # Sum of ISOLATED per-position collateral, and ABSOLUTE notional.
        self.assertEqual(summary["totalMarginUsed"], "99.95")
        self.assertEqual(summary["totalNtlPos"], "638.0")

    def test_margin_health_is_computed_from_api_ratios(self):
        data = adapter().call_tool("strategy_get_clearinghouse_state")["data"]
        # marginRatio 0.15 vs maintenance 0.05 -> 3.0x -> SAFE
        self.assertEqual(
            data["main"]["assetPositions"][0]["position"]["marginHealth"], "SAFE"
        )

    def test_asset_data_serves_candles_open_interest_and_funding(self):
        result = adapter().call_tool(
            "market_get_asset_data",
            {"asset": "BTC", "candle_intervals": ["1h"], "dex": "xyz"},
        )
        data = result["data"]
        self.assertEqual(data["symbol"], "BTC")
        self.assertEqual(data["asset_context"]["openInterest"], 1234.5)
        self.assertEqual(data["asset_context"]["markPx"], 63510.0)
        self.assertEqual(data["candles"]["1h"][0]["c"], "63500.0")
        # oi_velocity has no Aftermath source and is deliberately absent.
        self.assertNotIn("oi_velocity", data)

    def test_a_dex_argument_is_accepted_and_discarded(self):
        instance = adapter()
        instance.call_tool("market_get_asset_data", {"asset": "BTC", "dex": "xyz"})
        for _path, body in instance._test_transport.calls:
            self.assertNotIn("dex", body)
            for value in body.values():
                if isinstance(value, str):
                    self.assertFalse(value.lower().startswith("xyz:"))

    def test_candle_resolutions_use_the_v3_enum_never_intervalMs(self):
        instance = adapter()
        instance.call_tool(
            "market_get_asset_data", {"asset": "BTC", "candle_intervals": ["1h", "4h"]}
        )
        candle_calls = [
            body
            for path, body in instance._test_transport.calls
            if path == "/api/perpetuals/market/candle-history"
        ]
        self.assertEqual(len(candle_calls), 2)
        for body in candle_calls:
            self.assertIn(body["resolution"], {"1h", "4h"})
            self.assertNotIn("intervalMs", body)
            self.assertNotIn("interval_ms", body)

    def test_instrument_list_reports_market_ids_and_derived_leverage(self):
        data = adapter().call_tool("market_list_instruments")["data"]
        self.assertEqual(data["count"], 2)
        btc = next(i for i in data["instruments"] if i["symbol"] == "BTC")
        self.assertEqual(btc["marketId"], BTC)
        self.assertEqual(btc["lotSize"], "1000n")
        self.assertAlmostEqual(btc["maxLeverage"], 10.0)

    def test_open_orders_use_accountNumber_and_chId(self):
        instance = adapter()
        instance.call_tool("strategy_get_open_orders", {"asset": "BTC"})
        path, body = instance._test_transport.calls[-1]
        self.assertEqual(path, "/api/ccxt/myPendingOrders")
        # CCXT READ: a plain number, plus the market id under chId.
        self.assertEqual(body, {"accountNumber": 7, "chId": BTC})

    def test_audit_query_paginates_with_the_documented_cursor(self):
        pages = [
            {"orders": [{"i": 1}], "nextBeforeTimestampCursor": 100},
            {"orders": [{"i": 2}], "nextBeforeTimestampCursor": None},
        ]

        def responder(_path, _body):
            return pages.pop(0) if pages else {"orders": []}

        instance = adapter(**{"/api/perpetuals/account/order-history": responder})
        result = instance.call_tool("audit_query", {"pages": 5})
        self.assertEqual(len(result["data"]["events"]), 2)
        cursor_bodies = [
            body
            for path, body in instance._test_transport.calls
            if path == "/api/perpetuals/account/order-history"
        ]
        self.assertEqual(cursor_bodies[1]["beforeTimestampCursor"], 100)
        # accountId goes out on the BigInt wire.
        self.assertEqual(cursor_bodies[0]["accountId"], "7n")

    def test_portfolio_reports_the_wallet_gap_instead_of_guessing(self):
        data = adapter().call_tool("account_get_portfolio")["data"]
        self.assertIsNone(data["walletBalances"])
        self.assertTrue(any("404" in gap for gap in data["gaps"]))

    def test_funding_regime_is_annualised_from_the_markets_own_frequency(self):
        data = adapter().call_tool("market_get_funding_regime")["data"]
        self.assertIn("BTC", data)
        self.assertEqual(data["BTC"]["fundingIntervalMs"], 3_600_000)
        self.assertIn(data["BTC"]["regime"], {"neutral", "tilted_long", "crowded_long"})

    def test_positions_are_requested_on_the_bigint_wire(self):
        instance = adapter()
        instance.call_tool("strategy_get_clearinghouse_state")
        body = next(
            body
            for path, body in instance._test_transport.calls
            if path == "/api/perpetuals/accounts/positions"
        )
        self.assertEqual(body, {"accountIds": ["7n"]})


class SafetyPostureTests(unittest.TestCase):
    def test_no_mutation_builds_while_disarmed(self):
        instance = adapter(armed=False)
        for tool, args in (
            ("strategy_create", {}),
            ("strategy_top_up", {"amount": 100}),
            ("strategy_pause", {}),
            ("strategy_open", {"asset": "BTC", "size": 100}),
        ):
            with self.subTest(tool=tool):
                with self.assertRaisesRegex(WriteDenied, "not armed"):
                    instance.call_tool(tool, args)

    def test_no_submit_route_is_reachable_from_any_transport(self):
        from aftermath_runtime import transport as transport_module

        allowlisted = (
            transport_module.READ_PATHS
            | transport_module.ADAPTER_READ_PATHS
            | transport_module.PREVIEW_PATHS
            | transport_module.BUILD_PATHS
        )
        self.assertFalse([p for p in allowlisted if "submit" in p])

    def test_a_tripped_breaker_blocks_every_mutation(self):
        from aftermath_runtime.errors import CircuitBreakerTripped
        from aftermath_runtime.safety import BotState

        instance = adapter(armed=True)
        instance.circuit_breaker.evaluate(BotState(drawdown_pct=99.0))
        with self.assertRaises(CircuitBreakerTripped):
            instance.call_tool("strategy_pause", {})

    def test_state_is_invalidated_after_a_mutation(self):
        instance = adapter(
            armed=True,
            **{
                "/api/perpetuals/transactions/create-account": SPONSORED_TX,
            },
        )
        instance.account()
        self.assertIsNotNone(instance._state.account)
        instance.call_tool("strategy_create", {})
        self.assertIsNone(instance._state.account)

    def test_strategy_close_is_honestly_refused_rather_than_faked(self):
        instance = adapter(armed=True)
        with self.assertRaisesRegex(WriteDenied, "multi-transaction"):
            instance.call_tool("strategy_close", {})

    def test_percent_of_withdrawable_sizing_is_refused(self):
        instance = adapter(armed=True)
        with self.assertRaisesRegex(Exception, "percent-of-withdrawable"):
            instance.call_tool("strategy_open", {"asset": "BTC", "marginPct": 20})


class KillSwitchIntegrationTests(unittest.TestCase):
    def test_cancellation_is_verified_by_re_reading_pending_orders(self):
        resting = [{"symbol": "BTC", "id": "1"}]
        state = {"cancelled": False}

        def pending(_path, body):
            return [] if state["cancelled"] else resting

        def cancel(_path, _body):
            state["cancelled"] = True
            return dict(SPONSORED_TX)

        instance = adapter(
            armed=True,
            **{
                "/api/ccxt/myPendingOrders": pending,
                "/api/perpetuals/account/transactions/cancel-orders": cancel,
                "/api/perpetuals/account/previews/cancel-orders": {
                    "collateralAmountOut": 0,
                    "collateralPrice": 1.0,
                },
            },
        )
        instance.kill_switch.trigger("test")
        self.assertTrue(instance.kill_switch.verified)

    def test_a_disarmed_runtime_reports_surviving_orders_rather_than_lying(self):
        from aftermath_runtime.errors import CircuitBreakerTripped

        instance = adapter(
            armed=False, **{"/api/ccxt/myPendingOrders": [{"symbol": "BTC", "id": "1"}]}
        )
        with self.assertRaises(CircuitBreakerTripped):
            instance.kill_switch.trigger("test")
        self.assertFalse(instance.kill_switch.verified)


class MockAdapterTests(unittest.TestCase):
    def test_it_runs_with_zero_network_and_zero_keys(self):
        mock = MockAftermathAdapter()
        data = mock.call_tool(
            "market_get_asset_data", {"asset": "BTC", "candle_intervals": ["1h"]}
        )["data"]
        self.assertEqual(len(data["candles"]["1h"]), 24)
        state = mock.call_tool("strategy_get_clearinghouse_state")["data"]
        self.assertEqual(state["main"]["marginSummary"]["accountValue"], "10000.0")

    def test_it_is_disarmed_by_default_too(self):
        with self.assertRaises(WriteDenied):
            MockAftermathAdapter().call_tool("strategy_top_up", {"amount": 1})

    def test_it_records_calls_for_assertions(self):
        mock = MockAftermathAdapter()
        mock.call_tool("market_list_instruments")
        self.assertEqual(mock.calls[0][0], "market_list_instruments")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
