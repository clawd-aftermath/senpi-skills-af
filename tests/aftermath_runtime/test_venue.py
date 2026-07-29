# Copyright 2026 Aftermath Finance. MIT License.
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from aftermath_runtime import (
    AftermathVenue,
    AmbiguousMarket,
    ContractError,
    ContractDriftError,
    FixtureTransport,
    MarketRegistry,
    MarketUnavailable,
    NativeCodec,
    NormalizationError,
    CANDLE_STREAM_PATH,
    UrllibReadTransport,
    WriteDenied,
    assert_runtime_enablement,
    market_candles_subscription,
)
from aftermath_runtime.stream import SnapshotStreamState
from aftermath_runtime.venue import (
    POSITIONS_ACCOUNT_IDS_DRIFT_CODE,
    reject_error_union,
)
from aftermath_runtime.models import (
    FIELD_DENOMINATIONS,
    PendingOrderRef,
    require_denomination,
    unsigned_bigint_wire,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def venue(**responses):
    defaults = {
        "/api/perpetuals/markets": fixture("markets.json"),
        "/api/perpetuals/markets/prices": fixture("prices.json"),
        "/api/perpetuals/market/candle-history": fixture("candles.json"),
        "/api/perpetuals/market/funding-history": fixture("funding.json"),
        "/api/perpetuals/accounts": fixture("account_caps.json"),
        "/api/perpetuals/accounts/positions": fixture("accounts_positions.json"),
        "/api/ccxt/myPendingOrders": fixture("open_orders.json"),
    }
    defaults.update(responses)
    transport = FixtureTransport(defaults)
    return AftermathVenue(transport), transport


class MarketRegistryTests(unittest.TestCase):
    def test_exact_resolution_and_dynamic_capabilities(self):
        registry = MarketRegistry.from_api(fixture("markets.json"))
        self.assertEqual(registry.resolve("BTC").market_id, "btc-market")
        self.assertEqual(registry.resolve("penny-market").symbol, "PENNY")
        self.assertEqual(
            registry.require("PENNY", ("candles", "funding")).funding_interval_ms,
            14_400_000,
        )

    def test_missing_market_fails_closed(self):
        registry = MarketRegistry.from_api(fixture("markets.json"))
        with self.assertRaises(MarketUnavailable):
            registry.resolve("ETH")

    def test_ambiguous_symbol_fails_closed(self):
        payload = fixture("markets.json")
        duplicate = json.loads(json.dumps(payload["marketDatas"][0]))
        duplicate["market"]["objectId"] = "btc-market-2"
        payload["marketDatas"].append(duplicate)
        with self.assertRaises(AmbiguousMarket):
            MarketRegistry.from_api(payload).resolve("BTC")

    def test_orderbook_only_openapi_shape_is_not_guessed(self):
        with self.assertRaises(NormalizationError):
            MarketRegistry.from_api({"orderbooks": []})

    def test_id_shaped_query_never_falls_through_to_symbol_matching(self):
        registry = MarketRegistry.from_api(fixture("markets.json"))
        with self.assertRaisesRegex(MarketUnavailable, "exact"):
            registry.resolve("0xdeadbeef")


class ReadNormalizationTests(unittest.TestCase):
    def test_prices_are_keyed_by_market_id_not_response_position(self):
        client, _ = venue()
        prices = client.get_prices(["BTC", "PENNY"])
        self.assertEqual(prices["btc-market"].mid_price, Decimal("63824.37"))
        self.assertEqual(prices["penny-market"].mid_price, Decimal("0.25"))

    def test_human_price_denomination_is_explicit_not_magnitude_inferred(self):
        self.assertEqual(
            FIELD_DENOMINATIONS[
                ("/api/perpetuals/markets/prices", "midPrice")
            ],
            "human_price",
        )
        with self.assertRaisesRegex(NormalizationError, "no human_price"):
            require_denomination(
                "/api/perpetuals/markets/prices", "unknownPrice", "human_price"
            )

    def test_mixed_human_and_b9_price_row_is_rejected(self):
        prices = fixture("prices.json")
        prices["marketsPrices"][0].update(
            {
                "midPrice": 250_000_000,
            }
        )
        client, _ = venue(**{"/api/perpetuals/markets/prices": prices})
        with self.assertRaises(NormalizationError):
            client.get_prices(["PENNY"])

    def test_candles_normalize_to_short_key_strings(self):
        client, transport = venue()
        candles = client.get_candles("BTC", "15m", 0, 1_800_000)
        self.assertEqual(candles[0].as_scanner_dict()["c"], "100.5")
        self.assertEqual(
            transport.calls[-1][1],
            {
                "marketId": "btc-market",
                "resolution": "15m",
                "fromTimestamp": 0,
                "toTimestamp": 1_800_000,
            },
        )

    def test_every_v3_candle_resolution_is_accepted(self):
        empty = {"candles": []}
        client, transport = venue(
            **{"/api/perpetuals/market/candle-history": empty}
        )
        resolutions = (
            "1m",
            "5m",
            "15m",
            "30m",
            "1h",
            "4h",
            "12h",
            "1d",
            "3d",
            "1w",
            "1mo",
        )
        for resolution in resolutions:
            with self.subTest(resolution=resolution):
                client.get_candles("BTC", resolution, 0, 10_000_000_000)
                self.assertEqual(
                    transport.calls[-1][1]["resolution"], resolution
                )

    def test_non_v3_candle_resolution_is_rejected_without_transport(self):
        client, transport = venue()
        before = list(transport.calls)
        for resolution in ("60m", "2h", "30d", "1y", 60_000):
            with self.subTest(resolution=resolution), self.assertRaises(
                NormalizationError
            ):
                client.get_candles(  # type: ignore[arg-type]
                    "BTC", resolution, 0, 10_000_000_000
                )
        self.assertEqual(transport.calls, before)

    def test_monthly_candle_uses_calendar_month_for_close_filtering(self):
        january_start = 1_735_689_600_000  # 2025-01-01T00:00:00Z
        february_start = 1_738_368_000_000  # 2025-02-01T00:00:00Z
        payload = {
            "candles": [
                {
                    "timestamp": january_start,
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100.5,
                    "volume": 12.5,
                }
            ]
        }
        client, _ = venue(
            **{"/api/perpetuals/market/candle-history": payload}
        )
        self.assertEqual(
            len(
                client.get_candles(
                    "BTC", "1mo", january_start, february_start - 1
                )
            ),
            0,
        )
        self.assertEqual(
            len(client.get_candles("BTC", "1mo", january_start, february_start)),
            1,
        )

    def test_monthly_candle_handles_december_and_leap_february(self):
        def milliseconds(year: int, month: int, day: int = 1) -> int:
            return int(
                datetime(
                    year, month, day, tzinfo=timezone.utc
                ).timestamp()
                * 1000
            )

        for start, end in (
            (milliseconds(2025, 12), milliseconds(2026, 1)),
            (milliseconds(2024, 2), milliseconds(2024, 3)),
        ):
            with self.subTest(start=start, end=end):
                payload = {
                    "candles": [
                        {
                            "timestamp": start,
                            "open": 100,
                            "high": 101,
                            "low": 99,
                            "close": 100.5,
                            "volume": 12.5,
                        }
                    ]
                }
                client, _ = venue(
                    **{"/api/perpetuals/market/candle-history": payload}
                )
                self.assertEqual(
                    len(client.get_candles("BTC", "1mo", start, end)), 1
                )

    def test_monthly_candle_rejects_unaligned_timestamp_fail_closed(self):
        january_31 = int(
            datetime(2025, 1, 31, tzinfo=timezone.utc).timestamp() * 1000
        )
        payload = {
            "candles": [
                {
                    "timestamp": january_31,
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100.5,
                    "volume": 12.5,
                }
            ]
        }
        client, _ = venue(
            **{"/api/perpetuals/market/candle-history": payload}
        )
        with self.assertRaisesRegex(NormalizationError, "UTC month start"):
            client.get_candles("BTC", "1mo", january_31, january_31 + 40 * 86_400_000)

    def test_in_progress_candle_is_excluded(self):
        payload = fixture("candles.json")
        payload["candles"].append(
            {
                "timestamp": 1_800_000,
                "open": 101,
                "high": 101.5,
                "low": 100.5,
                "close": 101.2,
                "volume": 1,
            }
        )
        client, _ = venue(
            **{"/api/perpetuals/market/candle-history": payload}
        )
        candles = client.get_candles("BTC", "15m", 0, 1_800_100)
        self.assertEqual([c.timestamp_ms for c in candles], [0, 900_000])

    def test_future_requested_end_is_clamped_to_injected_clock(self):
        payload = fixture("candles.json")
        payload["candles"].append(
            {
                "timestamp": 1_800_000,
                "open": 101,
                "high": 101.5,
                "low": 100.5,
                "close": 101.2,
                "volume": 1,
            }
        )
        transport = FixtureTransport(
            {
                "/api/perpetuals/markets": fixture("markets.json"),
                "/api/perpetuals/market/candle-history": payload,
            }
        )
        client = AftermathVenue(transport, now_ms=lambda: 1_800_100)
        candles = client.get_candles("BTC", "15m", 0, 3_600_000)
        self.assertEqual([c.timestamp_ms for c in candles], [0, 900_000])
        self.assertEqual(transport.calls[-1][1]["toTimestamp"], 1_800_100)

    def test_funding_carries_market_interval_without_hourly_assumption(self):
        client, _ = venue()
        funding = client.get_funding("BTC", 1, 3000)
        self.assertEqual(funding[0].interval_ms, 3_600_000)
        self.assertEqual(funding[0].long_rate, Decimal("0.00001"))

    def test_positions_wrapper_and_plural_account_ids_regression(self):
        client, transport = venue()
        account = client.get_account(7)
        self.assertEqual(account.account_id, 7)
        self.assertEqual(account.positions[0].market_id, "btc-market")
        self.assertEqual(
            transport.calls[-1],
            ("/api/perpetuals/accounts/positions", {"accountIds": ["7n"]}),
        )

    def test_positions_bigint_wire_choice_links_to_blocking_drift(self):
        drift = json.loads(
            (ROOT / "contracts" / "known-drift.json").read_text(
                encoding="utf-8"
            )
        )
        entry = next(
            item
            for item in drift["entries"]
            if item.get("code") == POSITIONS_ACCOUNT_IDS_DRIFT_CODE
        )
        self.assertTrue(entry["blocking"])
        self.assertEqual(entry["status"], "unresolved")
        client, transport = venue()
        client.get_positions(7)
        self.assertEqual(transport.calls[-1][1]["accountIds"], ["7n"])

    def test_numeric_account_id_is_not_capability_id(self):
        client, _ = venue()
        with self.assertRaises(NormalizationError):
            client.get_account("0xcap")  # type: ignore[arg-type]
        caps = client.get_account_caps([7])
        self.assertEqual(caps[7].capability_id, "0xcap")

    def test_account_caps_schema_keeps_plain_numeric_ids(self):
        client, transport = venue()
        client.get_account_caps([7])
        self.assertEqual(
            transport.calls[-1],
            ("/api/perpetuals/accounts", {"accountIds": [7]}),
        )

    def test_native_bigint_responses_reject_unsuffixed_values(self):
        positions = fixture("accounts_positions.json")
        positions["accounts"][0]["accountId"] = "7"
        client, _ = venue(
            **{"/api/perpetuals/accounts/positions": positions}
        )
        with self.assertRaisesRegex(ContractDriftError, "BigInt") as raised:
            client.get_account(7)
        self.assertEqual(
            raised.exception.as_dict(),
            {
                "code": "native_bigint_response_wire",
                "field": "accountId",
                "observedShape": "string_without_trailing_n",
            },
        )

    def test_u128_order_id_round_trips_without_numeric_coercion(self):
        maximum = 2**128 - 1
        row = fixture("accounts_positions.json")["accounts"][0]["positions"][0][
            "pendingOrders"
        ][0]
        row["orderId"] = f"{maximum}n"
        parsed = PendingOrderRef.from_api(row)
        self.assertEqual(parsed.order_id, maximum)
        self.assertIsInstance(parsed.order_id, int)
        self.assertEqual(
            unsigned_bigint_wire(parsed.order_id, "orderId"),
            f"{maximum}n",
        )

    def test_open_orders_use_numeric_account_and_market_object_id(self):
        contract = json.loads(
            (
                ROOT / "contracts" / "aftermath-skills-v3-contract.json"
            ).read_text(encoding="utf-8")
        )["expectations"]["ccxtPendingOrders"]
        client, transport = venue()
        orders = client.get_open_orders(7, "BTC")
        self.assertEqual(orders[0].order_id, "order-1")
        endpoint, request = transport.calls[-1]
        self.assertEqual(
            endpoint,
            contract["path"],
        )
        self.assertEqual(
            request,
            {
                contract["accountField"]: 7,
                contract["marketField"]: "btc-market",
            },
        )
        self.assertNotIn(contract["writeAccountField"], request)
        self.assertEqual(contract["writePolicy"], "deny")

    def test_http_200_error_union_is_rejected(self):
        with self.assertRaisesRegex(Exception, "success=false"):
            reject_error_union(
                {"success": False, "error": "preview failed"},
                endpoint="/api/perpetuals/account/previews/place-limit-order",
            )


class NativeCodecTests(unittest.TestCase):
    def test_btc_price_and_size_quantization(self):
        market = MarketRegistry.from_api(fixture("markets.json")).resolve("BTC")
        codec = NativeCodec(market)
        self.assertEqual(codec.price_to_native("63824.371139", "buy"), 63_824_371_100_000)
        self.assertEqual(codec.price_to_native("63824.371139", "sell"), 63_824_371_200_000)
        self.assertEqual(codec.size_to_native("0.0012345678"), 1_234_000)

    def test_sub_dollar_tick_and_lot_are_market_specific(self):
        market = MarketRegistry.from_api(fixture("markets.json")).resolve("PENNY")
        codec = NativeCodec(market)
        native = codec.price_to_native("0.250000019", "sell")
        self.assertEqual(native, 250_000_020)
        self.assertEqual(codec.price_from_native(native), Decimal("0.250000020"))
        self.assertEqual(codec.size_to_native("12.3456789"), 12_345_000_000)

    def test_bid_never_rounds_up_before_tick_floor(self):
        market = MarketRegistry.from_api(fixture("markets.json")).resolve("BTC")
        codec = NativeCodec(market)
        # Native value is 1,000,099,999.6: nearest-first would round onto the
        # next tick and violate a bid limit.
        self.assertEqual(
            codec.price_to_native("1.0000999996", "buy"), 1_000_000_000
        )

    def test_size_always_floors_below_one_lot(self):
        market = MarketRegistry.from_api(fixture("markets.json")).resolve("BTC")
        codec = NativeCodec(market)
        with self.assertRaisesRegex(NormalizationError, "below"):
            codec.size_to_native("0.0000009999")


class WriteBoundaryAndStreamTests(unittest.TestCase):
    def test_order_intent_is_always_denied(self):
        client, transport = venue()
        with self.assertRaises(WriteDenied):
            client.submit_order_intent({"asset": "BTC"})
        with self.assertRaises(WriteDenied):
            transport.post(
                "/api/perpetuals/account/transactions/place-limit-order", {}
            )

    def test_unresolved_drift_blocks_any_promotion_beyond_shadow(self):
        assert_runtime_enablement({"mode": "shadow", "write_policy": "deny"})
        with self.assertRaisesRegex(ContractError, "contract drift"):
            assert_runtime_enablement({"mode": "live", "write_policy": "allow"})
        with self.assertRaisesRegex(ContractError, "contract drift"):
            AftermathVenue(
                FixtureTransport({}),
                runtime_config={"mode": "live", "write_policy": "allow"},
            )

    def test_resolved_drift_still_cannot_promote_to_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            drift_path = Path(directory) / "resolved-drift.json"
            drift_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "blocking": True,
                                "status": "resolved",
                                "endpoint": "POST /api/perpetuals/markets",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(WriteDenied, "shadow mode"):
                assert_runtime_enablement(
                    {"mode": "live", "write_policy": "allow"},
                    drift_path=drift_path,
                )

    def test_live_read_transport_requires_two_explicit_opt_ins(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(WriteDenied, "allow_network"):
                UrllibReadTransport()
            with self.assertRaisesRegex(
                WriteDenied, "AFTERMATH_ALLOW_LIVE_READS"
            ):
                UrllibReadTransport(allow_network=True)
        with patch.dict(
            os.environ, {"AFTERMATH_ALLOW_LIVE_READS": "1"}, clear=True
        ):
            with self.assertRaisesRegex(WriteDenied, "allow_network"):
                UrllibReadTransport()
            transport = UrllibReadTransport(allow_network=True)
            with self.assertRaisesRegex(WriteDenied, "read-only transport"):
                transport.post(
                    "/api/perpetuals/account/transactions/place-limit-order",
                    {},
                )

    def test_live_read_transport_is_post_only_timeout_bounded_and_unauthenticated(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"marketDatas":[]}'

        with patch.dict(
            os.environ, {"AFTERMATH_ALLOW_LIVE_READS": "1"}, clear=True
        ):
            transport = UrllibReadTransport(
                allow_network=True, timeout_seconds=3.25
            )
            with patch(
                "aftermath_runtime.transport.urlopen",
                return_value=Response(),
            ) as request_mock:
                self.assertEqual(
                    transport.post("/api/perpetuals/markets", {}),
                    {"marketDatas": []},
                )
        request, = request_mock.call_args.args
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request_mock.call_args.kwargs["timeout"], 3.25)
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers, {"content-type": "application/json"})

    def test_no_module_selects_live_transport_as_a_default_or_fallback(self):
        roots = (
            ROOT / "aftermath_runtime",
            ROOT / "aftermath-overlay" / "shadow",
            ROOT / "tools",
        )
        callers = []
        pattern = re.compile(r"\bUrllibReadTransport\s*\(")
        for root in roots:
            for source in root.rglob("*.py"):
                if pattern.search(source.read_text(encoding="utf-8")):
                    callers.append(str(source.relative_to(ROOT)))
        self.assertEqual(callers, [])

    def test_stream_requires_new_snapshot_after_disconnect_or_gap(self):
        state = SnapshotStreamState()
        with self.assertRaisesRegex(Exception, "snapshot required"):
            state.apply_delta(sequence=1, updates={})
        state.replace_snapshot(sequence=4, rows={"one": {"price": 1}})
        state.apply_delta(sequence=5, updates={"one": {"price": 2}})
        self.assertEqual(state.rows["one"]["price"], 2)
        state.disconnected()
        with self.assertRaisesRegex(Exception, "snapshot required"):
            state.apply_delta(sequence=6, updates={})
        state.replace_snapshot(sequence=10, rows={})
        with self.assertRaisesRegex(Exception, "sequence gap"):
            state.apply_delta(sequence=12, updates={})
        self.assertFalse(state.synced)

    def test_v3_candles_use_general_updates_websocket_subscription(self):
        self.assertEqual(CANDLE_STREAM_PATH, "/api/perpetuals/ws/updates")
        self.assertEqual(
            market_candles_subscription("btc-market", "1w"),
            {
                "action": "subscribe",
                "subscriptionType": {
                    "marketCandles": {
                        "marketId": "btc-market",
                        "interval": "1w",
                    }
                },
            },
        )
        with self.assertRaisesRegex(ContractError, "resolution"):
            market_candles_subscription("btc-market", "604800000")


if __name__ == "__main__":
    unittest.main()
