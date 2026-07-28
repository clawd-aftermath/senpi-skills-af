#!/usr/bin/env python3
"""Regression tests for both self-contained legacy DSL price helpers."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPERS = (
    REPO_ROOT
    / "dsl-dynamic-stop-loss"
    / "scripts"
    / "aftermath_price.py",
    REPO_ROOT / "tiger-strategy" / "scripts" / "aftermath_price.py",
)


def load_helper(path: Path):
    module_name = "price_helper_" + "_".join(path.parts[-3:-1])
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LegacyPriceHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helpers = [load_helper(path) for path in HELPERS]

    def test_live_market_shape_prefers_exact_metadata_symbol(self):
        response = {
            "marketDatas": [
                {
                    "market": {
                        "objectId": "base-match",
                        "marketParams": {"baseAssetSymbol": "BTC"},
                    },
                    "metadata": {"symbol": "OTHER"},
                },
                {
                    "market": {
                        "objectId": "metadata-match",
                        "marketParams": {"baseAssetSymbol": "BTCUSD"},
                    },
                    "metadata": {"symbol": "BTC"},
                },
            ]
        }
        for helper in self.helpers:
            with self.subTest(helper=helper.__name__):
                self.assertEqual(
                    helper.resolve_market_id(response, "BTC"),
                    "metadata-match",
                )

    def test_fallback_market_shape_supports_object_id(self):
        response = {
            "markets": [
                {
                    "objectId": "btc-market",
                    "marketParams": {"baseAssetSymbol": "BTCUSD"},
                }
            ]
        }
        for helper in self.helpers:
            with self.subTest(helper=helper.__name__):
                self.assertEqual(
                    helper.resolve_market_id(response, "BTC"),
                    "btc-market",
                )

    def test_ambiguous_market_match_raises(self):
        response = {
            "marketDatas": [
                {
                    "market": {"objectId": "one"},
                    "metadata": {"symbol": "BTC"},
                },
                {
                    "market": {"objectId": "two"},
                    "metadata": {"symbol": "BTC"},
                },
            ]
        }
        for helper in self.helpers:
            with self.subTest(helper=helper.__name__):
                with self.assertRaises(helper.PriceResolutionError):
                    helper.resolve_market_id(response, "BTC")

    def test_price_rows_are_keyed_by_market_id_not_position(self):
        response = {
            "marketsPrices": [
                {
                    "marketId": "eth-market",
                    "midPrice": 3200.0,
                    "basePrice": 3201.0,
                },
                {
                    "marketId": "btc-market",
                    "midPrice": 63880.5372,
                    "basePrice": 63904.21987555,
                },
            ]
        }
        for helper in self.helpers:
            with self.subTest(helper=helper.__name__):
                self.assertEqual(
                    helper.extract_human_mid_price(
                        response, "btc-market"
                    ),
                    63880.5372,
                )

    def test_missing_price_row_raises(self):
        response = {
            "marketsPrices": [
                {
                    "marketId": "eth-market",
                    "midPrice": 3200.0,
                    "basePrice": 3201.0,
                }
            ]
        }
        for helper in self.helpers:
            with self.subTest(helper=helper.__name__):
                with self.assertRaises(helper.PriceResolutionError):
                    helper.extract_human_mid_price(
                        response, "btc-market"
                    )

    def test_human_price_is_returned_without_b9_scaling(self):
        response = {
            "marketsPrices": [
                {
                    "marketId": "btc-market",
                    "midPrice": 63880.5372,
                    "basePrice": 63904.21987555,
                    "markPrice": 63880.53728959284,
                }
            ]
        }
        for helper in self.helpers:
            with self.subTest(helper=helper.__name__):
                self.assertEqual(
                    helper.extract_human_mid_price(
                        response, "btc-market"
                    ),
                    63880.5372,
                )

    def test_b9_mismatch_is_rejected(self):
        response = {
            "marketsPrices": [
                {
                    "marketId": "btc-market",
                    "midPrice": 63_880.5372 * 1_000_000_000,
                    "basePrice": 63_904.21987555,
                }
            ]
        }
        for helper in self.helpers:
            with self.subTest(helper=helper.__name__):
                with self.assertRaises(helper.PriceResolutionError):
                    helper.extract_human_mid_price(
                        response, "btc-market"
                    )

    def test_fully_b9_scaled_row_is_rejected(self):
        response = {
            "marketsPrices": [
                {
                    "marketId": "btc-market",
                    "midPrice": 63_880.5372 * 1_000_000_000,
                    "basePrice": 63_904.21987555 * 1_000_000_000,
                    "markPrice": 63_880.53728959284 * 1_000_000_000,
                }
            ]
        }
        for helper in self.helpers:
            with self.subTest(helper=helper.__name__):
                with self.assertRaises(helper.PriceResolutionError):
                    helper.extract_human_mid_price(
                        response, "btc-market"
                    )

    def test_missing_human_reference_is_rejected(self):
        response = {
            "marketsPrices": [
                {
                    "marketId": "btc-market",
                    "midPrice": 63880.5372,
                }
            ]
        }
        for helper in self.helpers:
            with self.subTest(helper=helper.__name__):
                with self.assertRaises(helper.PriceResolutionError):
                    helper.extract_human_mid_price(
                        response, "btc-market"
                    )

    def test_helper_copies_are_identical(self):
        self.assertEqual(
            HELPERS[0].read_text(),
            HELPERS[1].read_text(),
        )

    def test_direct_file_invocation_imports_sibling_helper(self):
        scripts = (
            REPO_ROOT / "dsl-dynamic-stop-loss" / "scripts" / "dsl-v4.py",
            REPO_ROOT / "tiger-strategy" / "scripts" / "dsl-v4.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            state_file.write_text(json.dumps({"active": False}))
            environment = {
                **os.environ,
                "DSL_STATE_FILE": str(state_file),
            }
            for script in scripts:
                with self.subTest(script=script):
                    result = subprocess.run(
                        [sys.executable, str(script)],
                        cwd=REPO_ROOT,
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        json.loads(result.stdout),
                        {"status": "inactive"},
                    )


if __name__ == "__main__":
    unittest.main()
