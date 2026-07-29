"""Contract regressions found while auditing the legacy Aftermath PR."""

from __future__ import annotations

import sys
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from contracts import (  # noqa: E402
    ContractError,
    validate_cancel_and_place_body,
    validate_positions_request,
)


class PositionContractTests(unittest.TestCase):
    def test_positions_requires_account_ids_array(self) -> None:
        with self.assertRaisesRegex(ContractError, r"accountIds\[\]"):
            validate_positions_request({"accountId": 123})
        validate_positions_request({"accountIds": ["123n"]})

    def test_positions_rejects_empty_or_non_bigint_wire_ids(self) -> None:
        for payload in (
            {"accountIds": []},
            {"accountIds": [123]},
            {"accountIds": ["123"]},
            {"accountIds": ["0xcap"]},
        ):
            with self.subTest(payload=payload), self.assertRaises(ContractError):
                validate_positions_request(payload)


class CancelAndPlaceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.valid = {
            "walletAddress": "0x1",
            "marketId": "0x2",
            "orderType": 2,
            "reduceOnly": False,
            "hasPosition": False,
            "ordersToPlace": [],
        }

    def test_rejects_extra_account_id(self) -> None:
        with self.assertRaisesRegex(ContractError, "account identity"):
            validate_cancel_and_place_body({**self.valid, "accountId": 123})

    def test_rejects_extra_account_cap_id(self) -> None:
        with self.assertRaisesRegex(ContractError, "account identity"):
            validate_cancel_and_place_body(
                {**self.valid, "accountCapId": "0xdeadbeef"}
            )

    def test_accepts_route_neutral_order_body(self) -> None:
        validate_cancel_and_place_body(self.valid)

    def test_stricter_overlay_boundary_is_pinned_as_an_intentional_deviation(self) -> None:
        fixture = json.loads(
            (ROOT / "tests/fixtures/openapi-contract-snapshot.json").read_text()
        )
        observed = fixture["cancel_and_place"]["raw_openapi_observation"]
        self.assertEqual({"accountId", "accountCapId"}, set(observed))
        boundary = fixture["cancel_and_place"]["overlay_boundary"]
        self.assertEqual(
            {"accountId", "accountCapId"},
            set(boundary["forbidden_order_body_fields"]),
        )


if __name__ == "__main__":
    unittest.main()
