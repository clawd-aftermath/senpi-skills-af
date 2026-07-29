"""ID discipline, BigInt wire format, instrument normalisation, gas modes.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aftermath_runtime.config import (  # noqa: E402
    DEFAULT_API_BASE_URL,
    RuntimeConfig,
    api_base_url,
    assert_not_retired_host,
)
from aftermath_runtime.errors import ConfigError, NormalizationError  # noqa: E402
from aftermath_runtime.gas import (  # noqa: E402
    DEFAULT_GAS_BUDGET_MIST,
    GasConfig,
    check_gas_mode,
    gas_pool_request,
    parse_gas_mode,
    sponsor_from_pool,
)
from aftermath_runtime.ids import (  # noqa: E402
    AccountCapId,
    AccountNumber,
    MarketId,
    NativeAccountId,
    SuiAddress,
    from_bigint_wire,
    normalise_instrument,
    side_to_native,
    to_bigint_wire,
)

WALLET = "0x" + "ab" * 32
CAP = "0x" + "cd" * 32
MARKET = "0x" + "11" * 32


class IdTypingTests(unittest.TestCase):
    def test_the_three_account_identifiers_are_distinct_types(self):
        native = NativeAccountId(123)
        cap = AccountCapId(CAP)
        number = AccountNumber(123)
        self.assertNotEqual(native, number)
        self.assertNotEqual(native, cap)
        self.assertEqual(native.wire, "123n")
        self.assertEqual(native.as_number(), 123)
        self.assertEqual(number.value, 123)

    def test_capability_object_id_is_rejected_as_a_native_account_id(self):
        with self.assertRaisesRegex(NormalizationError, "AccountCapId"):
            NativeAccountId(CAP)

    def test_native_account_id_is_rejected_as_a_capability_id(self):
        with self.assertRaisesRegex(NormalizationError, "object id"):
            AccountCapId("123")
        with self.assertRaises(NormalizationError):
            AccountCapId("123n")

    def test_account_number_refuses_wire_strings_and_negatives(self):
        for bad in ("123n", "123", -1, True):
            with self.assertRaises(NormalizationError):
                AccountNumber(bad)  # type: ignore[arg-type]

    def test_native_account_id_accepts_both_wire_and_plain_forms(self):
        self.assertEqual(NativeAccountId("123n"), NativeAccountId(123))
        self.assertEqual(NativeAccountId("123"), NativeAccountId(123))

    def test_a_ticker_is_not_a_market_id(self):
        with self.assertRaisesRegex(NormalizationError, "ticker"):
            MarketId("BTC")
        self.assertEqual(MarketId(MARKET).value, MARKET)

    def test_sui_address_normalises_case(self):
        self.assertEqual(SuiAddress(WALLET.upper().replace("0X", "0x")).value, WALLET)


class BigIntWireTests(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(to_bigint_wire(0), "0n")
        self.assertEqual(from_bigint_wire("42n"), 42)

    def test_plain_numbers_are_rejected_on_the_response_side(self):
        for bad in (42, "42", "42N", None, "n"):
            with self.assertRaises(NormalizationError):
                from_bigint_wire(bad)

    def test_negatives_and_bools_are_rejected_on_the_request_side(self):
        for bad in (-1, True):
            with self.assertRaises(NormalizationError):
                to_bigint_wire(bad)  # type: ignore[arg-type]


class InstrumentNormalisationTests(unittest.TestCase):
    def test_hip3_prefix_is_stripped_not_repointed(self):
        self.assertEqual(normalise_instrument("xyz:GOLD"), "GOLD")
        self.assertEqual(normalise_instrument("XYZ:BRENTOIL"), "BRENTOIL")

    def test_perp_and_settlement_spellings_reduce_to_the_base_symbol(self):
        self.assertEqual(normalise_instrument("BTC-PERP"), "BTC")
        self.assertEqual(normalise_instrument("BTC/USDC:USDC"), "BTC")
        self.assertEqual(normalise_instrument(" eth "), "ETH")

    def test_side_enum_is_numeric_zero_bid_one_ask(self):
        self.assertEqual(side_to_native("buy"), 0)
        self.assertEqual(side_to_native("long"), 0)
        self.assertEqual(side_to_native("sell"), 1)
        self.assertEqual(side_to_native(1), 1)
        with self.assertRaises(NormalizationError):
            side_to_native("sideways")


class HostDisciplineTests(unittest.TestCase):
    def test_default_is_the_live_v2_preview_host(self):
        self.assertEqual(api_base_url({}), DEFAULT_API_BASE_URL)
        self.assertIn("v2-preview", DEFAULT_API_BASE_URL)

    def test_the_retired_host_fails_closed(self):
        retired = "https://" + "aftermath" + ".finance"
        with self.assertRaisesRegex(ConfigError, "retired"):
            assert_not_retired_host(retired)
        with self.assertRaises(ConfigError):
            RuntimeConfig(base_url=retired)

    def test_the_live_host_and_unrelated_hosts_pass(self):
        assert_not_retired_host(DEFAULT_API_BASE_URL)
        assert_not_retired_host("http://localhost:8080")

    def test_env_override_is_honoured(self):
        self.assertEqual(
            api_base_url({"AF_API_BASE_URL": "http://localhost:9000/"}),
            "http://localhost:9000",
        )


class GasModeTests(unittest.TestCase):
    def test_default_is_sponsored_and_all_three_modes_parse(self):
        self.assertEqual(parse_gas_mode(None), "sponsored")
        self.assertEqual(parse_gas_mode(""), "sponsored")
        for mode in ("sponsored", "self", "dynamic"):
            self.assertEqual(parse_gas_mode(mode.upper()), mode)
        with self.assertRaises(ConfigError):
            parse_gas_mode("free")

    def test_dynamic_mode_requires_the_operator_to_choose_the_gas_coin(self):
        with self.assertRaisesRegex(ConfigError, "gas coin"):
            GasConfig(mode="dynamic")
        gas = GasConfig(mode="dynamic", gas_coin_type="0x2::usdc::USDC")
        self.assertEqual(gas.gas_coin_type, "0x2::usdc::USDC")

    def test_gas_budget_is_always_written_explicitly(self):
        gas = GasConfig(mode="self")
        body = gas.apply_to_body({"marketId": MARKET})
        self.assertEqual(body["gasBudget"], str(DEFAULT_GAS_BUDGET_MIST))
        self.assertNotIn("sponsor", body)

    def test_sponsored_body_requires_a_resolved_sponsor(self):
        with self.assertRaisesRegex(ConfigError, "no sponsor"):
            GasConfig(mode="sponsored").apply_to_body({})
        gas = GasConfig(mode="sponsored", sponsor=SuiAddress(WALLET))
        body = gas.apply_to_body({})
        self.assertEqual(body["sponsor"], {"walletAddress": WALLET})
        self.assertIs(body["isSponsoredTx"], True)

    def test_apply_to_body_never_mutates_the_caller_body(self):
        original = {"marketId": MARKET}
        GasConfig(mode="self").apply_to_body(original)
        self.assertEqual(original, {"marketId": MARKET})

    def test_sponsor_and_sender_may_be_the_same_address(self):
        same = SuiAddress(WALLET)
        gas = GasConfig(mode="sponsored", sponsor=same)
        body = gas.apply_to_body({"walletAddress": WALLET})
        self.assertEqual(body["sponsor"]["walletAddress"], body["walletAddress"])

    def test_gas_pool_request_is_a_post_body_with_wallet_address(self):
        self.assertEqual(gas_pool_request(SuiAddress(WALLET)), {"walletAddress": WALLET})

    def test_dynamic_gas_request_carries_the_three_required_fields(self):
        gas = GasConfig(mode="dynamic", gas_coin_type="0x2::usdc::USDC")
        body = gas.dynamic_gas_request("BASE64TX", SuiAddress(WALLET))
        self.assertEqual(
            set(body), {"serializedTx", "walletAddress", "gasCoinType"}
        )

    def test_dynamic_gas_request_is_refused_in_other_modes(self):
        with self.assertRaises(ConfigError):
            GasConfig(mode="self").dynamic_gas_request("X", SuiAddress(WALLET))


class GasPreflightTests(unittest.TestCase):
    def test_sponsored_passes_when_the_pool_answers_with_a_sponsor(self):
        result = check_gas_mode(
            GasConfig(mode="sponsored"),
            wallet_address=SuiAddress(WALLET),
            pool_payload={
                "balance": 1_000,
                "walletAddress": WALLET,
                "whitelistedAddresses": [WALLET],
            },
        )
        self.assertTrue(result.ok)

    def test_sponsored_fails_actionably_when_the_pool_is_unreachable(self):
        result = check_gas_mode(
            GasConfig(mode="sponsored"),
            wallet_address=SuiAddress(WALLET),
            pool_error="connection refused",
        )
        self.assertFalse(result.ok)
        self.assertIn("AF_GAS_MODE=self", result.remedy or "")

    def test_sponsored_fails_when_the_wallet_is_not_whitelisted(self):
        result = check_gas_mode(
            GasConfig(mode="sponsored"),
            wallet_address=SuiAddress(WALLET),
            pool_payload={
                "balance": 1,
                "walletAddress": "0x" + "ee" * 32,
                "whitelistedAddresses": ["0x" + "ff" * 32],
            },
        )
        self.assertFalse(result.ok)

    def test_self_mode_requires_enough_sui_for_the_explicit_budget(self):
        gas = GasConfig(mode="self")
        self.assertFalse(
            check_gas_mode(
                gas, wallet_address=SuiAddress(WALLET), sui_balance_mist=0
            ).ok
        )
        self.assertTrue(
            check_gas_mode(
                gas,
                wallet_address=SuiAddress(WALLET),
                sui_balance_mist=DEFAULT_GAS_BUDGET_MIST,
            ).ok
        )

    def test_dynamic_mode_reports_that_it_cannot_be_pinged(self):
        result = check_gas_mode(
            GasConfig(mode="dynamic", gas_coin_type="0x2::usdc::USDC"),
            wallet_address=SuiAddress(WALLET),
        )
        self.assertTrue(result.ok)
        self.assertIn("transform endpoint", result.detail)

    def test_every_mode_fails_without_a_wallet_and_never_switches_silently(self):
        for mode, kwargs in (
            ("sponsored", {}),
            ("self", {}),
            ("dynamic", {"gas_coin_type": "0x2::usdc::USDC"}),
        ):
            result = check_gas_mode(
                GasConfig(mode=mode, **kwargs), wallet_address=None
            )
            self.assertFalse(result.ok)
            self.assertEqual(result.mode, mode)

    def test_sponsor_extraction_returns_none_rather_than_guessing(self):
        self.assertIsNone(sponsor_from_pool({"balance": 1}))
        self.assertEqual(
            sponsor_from_pool({"walletAddress": WALLET}), SuiAddress(WALLET)
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
