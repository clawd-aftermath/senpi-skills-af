"""Offline regression tests for the generated Aftermath coverage overlay."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from coverage_lib import build, classify, inventory  # noqa: E402


class CoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = json.loads(
            (ROOT / "aftermath-overlay/coverage-rules.json").read_text()
        )
        cls.packages = {package.id: package for package in inventory()}

    def test_inventory_matches_pinned_source(self) -> None:
        self.assertEqual(99, len(self.packages))
        self.assertEqual(
            125, sum(len(package.instances) for package in self.packages.values())
        )

    def test_build_is_deterministic_and_partition_is_exhaustive(self) -> None:
        first = build()
        second = build()
        self.assertEqual(first, second)
        coverage = json.loads(first["coverage.json"])
        meta = coverage["meta"]
        self.assertEqual(
            meta["source_package_count"],
            meta["invariant"]["enabled_plus_blocked"],
        )
        self.assertTrue(meta["invariant"]["holds"])
        self.assertEqual(0, meta["enabled_count"])

    def test_universe_ranking_fails_closed_with_one_market(self) -> None:
        dynamic = self.packages["caribou"]
        # Runtime quarantine wins for Caribou, so use another dynamic-universe package.
        dynamic = next(
            package
            for package in self.packages.values()
            if not package.assets
            and package.id
            not in self.rules["blocked_runtime_semantics"]
            and not any(
                any(marker.lower() in literal.lower() for literal in package.code_literals)
                for marker in self.rules["derived_data_markers"]
            )
        )
        classification, reasons = classify(dynamic, self.rules)
        self.assertEqual("blocked-market", classification)
        self.assertIn("one active market", reasons[0])

    def test_initial_candidates_need_mapping(self) -> None:
        for package_id in ("rooster", "coyote", "gecko", "koala", "terrapin"):
            classification, _ = classify(self.packages[package_id], self.rules)
            self.assertEqual("needs-field-mapping", classification, package_id)

    def test_one_market_snapshot_is_explicit(self) -> None:
        self.assertEqual(["BTC"], self.rules["active_market_symbols"])
        snapshot = self.rules["active_market_snapshot"]
        self.assertIn("/api/ccxt/markets", snapshot["source"])
        self.assertRegex(snapshot["observed_at_utc"], r"^2026-07-28T")

    def test_enabled_can_only_come_from_explicit_supported_rules(self) -> None:
        coverage = json.loads(build()["coverage.json"])
        enabled = {
            package["id"] for package in coverage["packages"] if package["enabled"]
        }
        self.assertLessEqual(enabled, set(self.rules["supported"]))
        for package in coverage["packages"]:
            self.assertEqual(
                package["classification"] == "supported", package["enabled"]
            )
            self.assertTrue(package["rule_id"])
            self.assertIn("matched_marker", package)

    def test_margin_semantic_defects_are_quarantined(self) -> None:
        for package_id in ("caribou", "dire", "hydra", "spider"):
            classification, reasons = classify(self.packages[package_id], self.rules)
            self.assertEqual("blocked-runtime-semantics", classification)
            self.assertTrue(any("margin" in reason.lower() for reason in reasons))


if __name__ == "__main__":
    unittest.main()
