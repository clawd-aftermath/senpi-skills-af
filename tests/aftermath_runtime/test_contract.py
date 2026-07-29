# Copyright 2026 Aftermath Finance. MIT License.
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ContractTests(unittest.TestCase):
    def test_selected_contract_is_pinned_and_has_required_read_paths(self):
        contract = json.loads(
            (ROOT / "contracts" / "selected-openapi-contract.json").read_text()
        )
        self.assertEqual(
            contract["source"]["canonicalSha256"],
            "5bf4f1322ae79561c42bff9329950b757558aea79cce63e89145382024d072f2",
        )
        self.assertEqual(len(contract["paths"]), 8)
        for path in (
            "/api/perpetuals/markets",
            "/api/perpetuals/market/candle-history",
            "/api/perpetuals/accounts/positions",
            "/api/ccxt/myPendingOrders",
        ):
            self.assertIn(path, contract["paths"])

    def test_positions_contract_uses_plural_numeric_account_ids(self):
        contract = json.loads(
            (ROOT / "contracts" / "selected-openapi-contract.json").read_text()
        )
        operation = contract["paths"]["/api/perpetuals/accounts/positions"]["post"]
        ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        schema = contract["schemas"][ref.rsplit("/", 1)[-1]]
        self.assertIn("accountIds", schema["required"])
        self.assertEqual(schema["properties"]["accountIds"]["type"], "array")
        self.assertEqual(
            schema["properties"]["accountIds"]["items"]["type"], "integer"
        )

    def test_runtime_schema_forces_shadow_deny_and_explicit_sizing(self):
        schema = json.loads(
            (ROOT / "schemas" / "aftermath-runtime-v1.schema.json").read_text()
        )
        self.assertEqual(schema["properties"]["mode"]["const"], "shadow")
        self.assertEqual(schema["properties"]["write_policy"]["const"], "deny")
        required = schema["properties"]["sizing_semantics"]["required"]
        self.assertIn("margin_pct_basis", required)
        self.assertIn("native_price_unit", required)
        config = json.loads(
            (
                ROOT
                / "aftermath-overlay"
                / "shadow"
                / "harness"
                / "rooster"
                / "main"
                / "aftermath-runtime.json"
            ).read_text()
        )
        self.assertEqual(config["schema_version"], "aftermath/v1")
        self.assertEqual(config["write_policy"], "deny")
        self.assertEqual(
            set(config["sizing_semantics"]), set(required)
        )

    def test_openapi_markets_response_drift_is_machine_readable_and_blocking(self):
        drift = json.loads(
            (ROOT / "contracts" / "known-drift.json").read_text()
        )
        self.assertEqual(
            drift["sourceContractCanonicalSha256"],
            "5bf4f1322ae79561c42bff9329950b757558aea79cce63e89145382024d072f2",
        )
        self.assertEqual(len(drift["entries"]), 2)
        endpoints = {entry["endpoint"] for entry in drift["entries"]}
        self.assertEqual(
            endpoints,
            {
                "POST /api/perpetuals/markets",
                "POST /api/perpetuals/market/candle-history",
            },
        )
        self.assertTrue(all(entry["blocking"] for entry in drift["entries"]))
        self.assertTrue(
            all(entry["status"] == "unresolved" for entry in drift["entries"])
        )


if __name__ == "__main__":
    unittest.main()
