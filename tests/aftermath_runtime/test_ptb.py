"""The PTB pipeline: preview union, the inspection gate, signing, reconcile.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import base64
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aftermath_runtime.errors import (  # noqa: E402
    ContractError,
    InspectionFailed,
    PreviewRejected,
    WriteDenied,
)
from aftermath_runtime.execution import (  # noqa: E402
    AccountRef,
    ExecutionClient,
    OrderToPlace,
    assert_no_venue_leakage,
    encode_bigints,
)
from aftermath_runtime.gas import GasConfig  # noqa: E402
from aftermath_runtime.ids import (  # noqa: E402
    MarketId,
    NativeAccountId,
    SuiAddress,
)
from aftermath_runtime.ptb import (  # noqa: E402
    InspectedTx,
    PreviewError,
    PreviewOk,
    PtbPipeline,
    TxIntent,
    headers_signal_error,
    inspect,
    parse_preview,
    reconcile,
    sign_inspected,
    submit,
)
from aftermath_runtime.transport import AdapterFixtureTransport  # noqa: E402

WALLET = SuiAddress("0x" + "ab" * 32)
MARKET = MarketId("0x" + "11" * 32)
TX_KIND = base64.b64encode(b"transaction-kind").decode()
DIGEST = base64.b64encode(b"digest").decode()
SELF_GAS = GasConfig(mode="self")
SPONSORED_GAS = GasConfig(mode="sponsored", sponsor=WALLET)


def intent(gas: GasConfig = SELF_GAS, **kwargs) -> TxIntent:
    defaults = dict(
        intent="test",
        sender=WALLET,
        gas=gas,
        build_path="/api/perpetuals/account/transactions/place-limit-order",
    )
    defaults.update(kwargs)
    return TxIntent(**defaults)  # type: ignore[arg-type]


class PreviewUnionTests(unittest.TestCase):
    def test_http_200_with_an_error_body_is_an_error_arm(self):
        result = parse_preview({"error": "insufficient collateral"}, endpoint="/p")
        self.assertIsInstance(result, PreviewError)
        self.assertEqual(result.error, "insufficient collateral")

    def test_the_success_arm_is_recognised(self):
        result = parse_preview(
            {"collateralAmountOut": 123, "collateralPrice": 1.0}, endpoint="/p"
        )
        self.assertIsInstance(result, PreviewOk)
        self.assertEqual(result.collateral_amount_out, 123)

    def test_bigint_wire_amounts_are_accepted(self):
        result = parse_preview(
            {"collateralAmountOut": "123n", "collateralPrice": 1.0}, endpoint="/p"
        )
        self.assertEqual(result.collateral_amount_out, 123)

    def test_an_unrecognised_shape_fails_closed(self):
        for payload in ({}, [], None, {"ok": True}, {"collateralAmountOut": 1}):
            with self.subTest(payload=payload):
                self.assertIsInstance(
                    parse_preview(payload, endpoint="/p"), PreviewError
                )

    def test_the_error_header_is_recognised(self):
        self.assertTrue(headers_signal_error({"X-Error-Message": "true"}))
        self.assertTrue(headers_signal_error({"x-error-message": "TRUE"}))
        self.assertFalse(headers_signal_error({"x-error-message": "false"}))
        self.assertFalse(headers_signal_error(None))


class InspectionGateTests(unittest.TestCase):
    def test_inspected_tx_cannot_be_forged(self):
        with self.assertRaisesRegex(InspectionFailed, "not bypassable"):
            InspectedTx(tx_kind=TX_KIND, intent=intent())

    def test_a_forged_token_is_still_rejected(self):
        with self.assertRaises(InspectionFailed):
            InspectedTx(tx_kind=TX_KIND, intent=intent(), _token=object())

    def test_the_gate_token_cannot_be_harvested_off_an_instance(self):
        good = inspect({"txKind": TX_KIND}, intent())
        # The token is cleared after validation, so it cannot be reused.
        self.assertIsNone(good._token)
        with self.assertRaises(InspectionFailed):
            InspectedTx(tx_kind="forged", intent=intent(), _token=good._token)

    def test_dataclasses_replace_cannot_launder_a_mutation_past_the_gate(self):
        good = inspect({"txKind": TX_KIND}, intent())
        with self.assertRaises(InspectionFailed):
            dataclasses.replace(good, tx_kind="tampered")

    def test_with_digest_is_the_only_sanctioned_mutation(self):
        good = inspect({"txKind": TX_KIND}, intent())
        signed_ready = good.with_digest(DIGEST)
        self.assertEqual(signed_ready.signing_digest, DIGEST)
        self.assertEqual(signed_ready.tx_kind, TX_KIND)
        with self.assertRaises(InspectionFailed):
            good.with_digest("not base64!!")

    def test_the_documented_txkind_shape_is_required(self):
        for payload in (None, [], {}, {"transactionBytes": "abcd"}, {"txKind": ""}):
            with self.subTest(payload=payload):
                with self.assertRaises(InspectionFailed):
                    inspect(payload, intent())

    def test_txkind_must_be_real_base64(self):
        with self.assertRaisesRegex(InspectionFailed, "base64"):
            inspect({"txKind": "not base64!!"}, intent())

    def test_raw_transaction_bytes_are_never_signed(self):
        with self.assertRaisesRegex(InspectionFailed, "transactionBytes"):
            inspect({"txKind": TX_KIND, "transactionBytes": TX_KIND}, intent())

    def test_a_sender_mismatch_is_caught(self):
        other = "0x" + "cd" * 32
        with self.assertRaisesRegex(InspectionFailed, "sender mismatch"):
            inspect({"txKind": TX_KIND, "walletAddress": other}, intent())

    def test_a_package_mismatch_is_caught(self):
        with self.assertRaisesRegex(InspectionFailed, "package mismatch"):
            inspect(
                {"txKind": TX_KIND, "packageId": "0xdead"},
                intent(expected_package="0xbeef"),
            )

    def test_self_gas_must_not_come_back_sponsored(self):
        with self.assertRaisesRegex(InspectionFailed, "'self'"):
            inspect({"txKind": TX_KIND, "sponsorSignature": "sig"}, intent())

    def test_sponsored_gas_must_come_back_sponsored(self):
        with self.assertRaisesRegex(InspectionFailed, "no sponsor signature"):
            inspect({"txKind": TX_KIND}, intent(gas=SPONSORED_GAS))
        ok = inspect(
            {"txKind": TX_KIND, "sponsorSignature": "sig"}, intent(gas=SPONSORED_GAS)
        )
        self.assertEqual(ok.sponsor_signature, "sig")

    def test_sponsor_equal_to_sender_is_allowed(self):
        # Sponsor and sender MAY be the same Sui address.
        gas = GasConfig(mode="sponsored", sponsor=WALLET)
        tx = inspect(
            {"txKind": TX_KIND, "walletAddress": str(WALLET), "sponsorSignature": "s"},
            intent(gas=gas),
        )
        self.assertEqual(tx.tx_kind, TX_KIND)

    def test_defer_share_must_return_deferred_references(self):
        with self.assertRaisesRegex(InspectionFailed, "deferred"):
            inspect({"txKind": TX_KIND}, intent(expects_deferred=True))
        with self.assertRaisesRegex(InspectionFailed, "missing"):
            inspect(
                {"txKind": TX_KIND, "deferred": {"accountArg": 1}},
                intent(expects_deferred=True),
            )
        tx = inspect(
            {
                "txKind": TX_KIND,
                "deferred": {
                    "accountArg": 1,
                    "adminCapArg": 2,
                    "sharePolicyArg": 3,
                    "collateralCoinType": "0x2::sui::SUI",
                },
            },
            intent(expects_deferred=True),
        )
        self.assertEqual(tx.deferred["adminCapArg"], 2)


class SigningTests(unittest.TestCase):
    def test_signing_requires_arming(self):
        tx = inspect({"txKind": TX_KIND}, intent()).with_digest(DIGEST)
        with self.assertRaisesRegex(WriteDenied, "not armed"):
            sign_inspected(tx, [lambda d: "sig"])

    def test_signing_requires_a_digest_never_the_bytes(self):
        tx = inspect({"txKind": TX_KIND}, intent())
        with self.assertRaisesRegex(InspectionFailed, "signing digest"):
            sign_inspected(tx, [lambda d: "sig"], armed=True)

    def test_signatures_are_always_a_list_plural(self):
        tx = inspect({"txKind": TX_KIND}, intent()).with_digest(DIGEST)
        seen: list[str] = []

        def signer(digest: str) -> str:
            seen.append(digest)
            return f"sig:{digest}"

        signatures = sign_inspected(tx, [signer, signer], armed=True)
        self.assertEqual(len(signatures), 2)
        # Both signers sign the SAME digest.
        self.assertEqual(seen, [DIGEST, DIGEST])

    def test_only_an_inspected_tx_can_be_signed(self):
        with self.assertRaises(InspectionFailed):
            sign_inspected({"txKind": TX_KIND}, [lambda d: "s"], armed=True)  # type: ignore[arg-type]

    def test_submission_is_refused_outright(self):
        with self.assertRaisesRegex(WriteDenied, "never broadcasts"):
            submit()


class PipelineTests(unittest.TestCase):
    def build_transport(self, **overrides):
        responses = {
            "/api/perpetuals/account/previews/place-limit-order": {
                "collateralAmountOut": 100,
                "collateralPrice": 1.0,
            },
            "/api/perpetuals/account/transactions/place-limit-order": {
                "txKind": TX_KIND
            },
        }
        responses.update(overrides)
        return AdapterFixtureTransport(responses)

    def test_a_preview_error_blocks_the_build_entirely(self):
        transport = self.build_transport(
            **{
                "/api/perpetuals/account/previews/place-limit-order": {
                    "error": "too big"
                }
            }
        )
        pipeline = PtbPipeline(transport)
        with self.assertRaisesRegex(PreviewRejected, "too big"):
            pipeline.build(
                intent(),
                {"marketId": str(MARKET)},
                preview_path="/api/perpetuals/account/previews/place-limit-order",
            )
        # The build route was never called.
        self.assertEqual(
            [path for path, _ in transport.calls],
            ["/api/perpetuals/account/previews/place-limit-order"],
        )

    def test_a_passing_preview_lets_the_build_through_and_inspects_it(self):
        transport = self.build_transport()
        pipeline = PtbPipeline(transport)
        tx = pipeline.build(
            intent(),
            {"marketId": str(MARKET)},
            preview_path="/api/perpetuals/account/previews/place-limit-order",
        )
        self.assertEqual(tx.tx_kind, TX_KIND)
        # The gas budget was written explicitly on the build body.
        build_body = transport.calls[-1][1]
        self.assertIn("gasBudget", build_body)

    def test_a_transport_failure_during_preview_fails_closed(self):
        pipeline = PtbPipeline(AdapterFixtureTransport({}))
        result = pipeline.preview(
            "/api/perpetuals/account/previews/place-limit-order", {}
        )
        self.assertIsInstance(result, PreviewError)


class ReconcileTests(unittest.TestCase):
    def test_it_succeeds_once_state_is_observed(self):
        seen = [False, False, True]
        reconcile(lambda: seen.pop(0), attempts=3)

    def test_it_raises_when_state_never_arrives(self):
        with self.assertRaisesRegex(ContractError, "reconciliation failed"):
            reconcile(lambda: False, attempts=2, intent="deposit")


class ExecutionClientTests(unittest.TestCase):
    def account(self) -> AccountRef:
        return AccountRef(NativeAccountId(7), WALLET)

    def client(self, responses=None, armed=True) -> ExecutionClient:
        base = {
            "/api/perpetuals/account/transactions/cancel-and-place-orders": {
                "txKind": TX_KIND
            },
            "/api/perpetuals/account/transactions/place-scale-order": {
                "txKind": TX_KIND
            },
            "/api/perpetuals/account/previews/place-scale-order": {
                "collateralAmountOut": 1,
                "collateralPrice": 1.0,
            },
            "/api/perpetuals/transactions/create-account": {
                "txKind": TX_KIND,
                "deferred": {
                    "accountArg": 1,
                    "adminCapArg": 2,
                    "sharePolicyArg": 3,
                    "collateralCoinType": "0x2::sui::SUI",
                },
            },
        }
        base.update(responses or {})
        self.transport = AdapterFixtureTransport(base)
        return ExecutionClient(self.transport, gas=SELF_GAS, armed=armed)

    def test_nothing_builds_unless_armed(self):
        client = self.client(armed=False)
        with self.assertRaisesRegex(WriteDenied, "not armed"):
            client.cancel_and_place(
                self.account(), MARKET, orders_to_place=[OrderToPlace(0, 100, 10)]
            )
        self.assertEqual(self.transport.calls, [])

    def test_a_requote_is_ONE_transaction(self):
        client = self.client()
        client.cancel_and_place(
            self.account(),
            MARKET,
            order_ids_to_cancel=[1, 2],
            orders_to_place=[OrderToPlace("buy", 100, 10)],
        )
        paths = [path for path, _ in self.transport.calls]
        self.assertEqual(
            paths, ["/api/perpetuals/account/transactions/cancel-and-place-orders"]
        )
        body = self.transport.calls[0][1]
        self.assertEqual(body["orderIdsToCancel"], ["1n", "2n"])
        self.assertEqual(body["ordersToPlace"][0]["price"], "100n")
        self.assertEqual(body["ordersToPlace"][0]["side"], 0)
        # A requote aborts rather than double-quoting over an unobserved fill.
        self.assertIs(body["shouldAbortOnMissingId"], True)

    def test_a_ladder_is_ONE_transaction_and_is_preview_gated(self):
        client = self.client()
        client.place_scale_order(
            self.account(),
            MARKET,
            side="sell",
            start_price_native=100,
            end_price_native=200,
            number_of_orders=5,
            total_size_native=500,
            collateral_change=100.0,
        )
        paths = [path for path, _ in self.transport.calls]
        self.assertEqual(
            paths,
            [
                "/api/perpetuals/account/previews/place-scale-order",
                "/api/perpetuals/account/transactions/place-scale-order",
            ],
        )
        body = self.transport.calls[-1][1]
        self.assertEqual(body["numberOfOrders"], 5)
        self.assertEqual(body["totalSize"], "500n")
        self.assertEqual(body["side"], 1)

    def test_onboarding_uses_defer_share_and_gets_deferred_refs(self):
        client = self.client()
        tx = client.build_onboarding_ptb(
            WALLET, collateral_coin_type="0x2::sui::SUI", deposit_amount=1_000
        )
        body = self.transport.calls[-1][1]
        self.assertIs(body["deferShare"], True)
        self.assertEqual(tx.deferred["accountArg"], 1)

    def test_a_cancel_all_does_not_abort_on_a_missing_order(self):
        client = self.client(
            {
                "/api/perpetuals/account/transactions/cancel-orders": {
                    "txKind": TX_KIND
                },
                "/api/perpetuals/account/previews/cancel-orders": {
                    "collateralAmountOut": 0,
                    "collateralPrice": 1.0,
                },
            }
        )
        client.cancel_orders(self.account(), {str(MARKET): {"orderIds": []}})
        body = self.transport.calls[-1][1]
        self.assertIs(body["shouldAbortOnMissingId"], False)

    def test_empty_requotes_are_refused(self):
        client = self.client()
        with self.assertRaises(Exception):
            client.cancel_and_place(self.account(), MARKET)


class WireEncodingTests(unittest.TestCase):
    def test_only_documented_bigint_fields_are_converted(self):
        body = encode_bigints(
            {
                "price": 100,
                "size": 5,
                "accountId": 7,
                "leverage": 5.0,
                "slippage": 0.01,
                "numberOfOrders": 3,
                "reduceOnly": False,
                "marketId": str(MARKET),
            }
        )
        self.assertEqual(body["price"], "100n")
        self.assertEqual(body["size"], "5n")
        self.assertEqual(body["accountId"], "7n")
        # Plain-number fields stay plain: this is NOT a blanket conversion.
        self.assertEqual(body["leverage"], 5.0)
        self.assertEqual(body["numberOfOrders"], 3)
        self.assertIs(body["reduceOnly"], False)

    def test_none_passes_through_untouched(self):
        self.assertIsNone(encode_bigints({"price": None})["price"])

    def test_already_encoded_values_are_left_alone(self):
        self.assertEqual(encode_bigints({"size": "9n"})["size"], "9n")


class VenueLeakageTests(unittest.TestCase):
    def test_hyperliquid_sizing_fields_are_rejected(self):
        for field in ("marginPct", "margin_pct", "coin", "szi", "destinationDex"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(Exception, "leaked"):
                    assert_no_venue_leakage({field: 1})

    def test_hip3_prefixed_values_are_rejected(self):
        with self.assertRaisesRegex(Exception, "HIP-3"):
            assert_no_venue_leakage({"marketId": "xyz:GOLD"})

    def test_a_clean_aftermath_body_passes(self):
        assert_no_venue_leakage(
            {"marketId": str(MARKET), "size": "5n", "leverage": 5.0}
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
