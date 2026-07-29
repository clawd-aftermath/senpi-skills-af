"""Offline regressions for the pinned Aftermath skills v3 contract."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from aftermath_runtime.stream import CANDLE_RESOLUTIONS, CANDLE_STREAM_PATH

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from validate_skills_contract import (  # noqa: E402
    CONTRACT_PATH,
    EXPECTED_COMMIT,
    EXPECTED_FILES,
    EXPECTED_IMPLEMENTATION_STATUS,
    EXPECTED_RESOLUTIONS,
    validate,
)


class SkillsContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_immutable_source_and_extracted_contract_are_current(self) -> None:
        validate()
        source = self.contract["source"]
        self.assertEqual(source["commit"], EXPECTED_COMMIT)
        self.assertEqual(source["files"], EXPECTED_FILES)
        self.assertEqual(source["license"], "Apache-2.0")
        self.assertEqual(
            source["fileDigestAlgorithm"],
            "sha256 of raw file bytes stored at the pinned git commit",
        )

    def test_v3_wire_and_stream_contract_is_exact(self) -> None:
        expected = self.contract["expectations"]
        self.assertEqual(expected["candles"]["resolutions"], EXPECTED_RESOLUTIONS)
        self.assertEqual(CANDLE_RESOLUTIONS, frozenset(EXPECTED_RESOLUTIONS))
        self.assertEqual(expected["candles"]["historyField"], "resolution")
        self.assertEqual(
            expected["candles"]["streamPath"], "/api/perpetuals/ws/updates"
        )
        self.assertEqual(CANDLE_STREAM_PATH, expected["candles"]["streamPath"])
        self.assertEqual(
            expected["identifiers"]["nativeBigIntWirePattern"], "^[0-9]+n$"
        )

    def test_removed_v3_fields_and_routes_are_pinned_fail_closed(self) -> None:
        expected = self.contract["expectations"]
        self.assertEqual(
            expected["builderCode"]["allowedFields"],
            ["integratorId", "integratorFee"],
        )
        self.assertEqual(
            expected["slTp"]["allowedPriceFields"],
            ["stopLossPrice", "takeProfitPrice"],
        )
        self.assertEqual(
            expected["slTp"]["triggerPriceType"],
            {"0": "index", "1": "book_mid", "2": "mark"},
        )
        self.assertEqual(len(expected["removedIntegratorRoutes"]), 3)
        self.assertEqual(
            expected["implementationStatus"], EXPECTED_IMPLEMENTATION_STATUS
        )
        self.assertTrue(
            all(
                status != "implemented"
                for semantic, status in expected["implementationStatus"].items()
                if semantic
                in {
                    "builderCode",
                    "isolatedMarginAllocation",
                    "runtimeSafety.deadManAndSerialization",
                    "signingAndSubmit",
                    "slTp",
                }
            )
        )

    def test_safety_contract_cannot_silently_promote(self) -> None:
        expected = self.contract["expectations"]
        self.assertEqual(expected["writePolicy"], "deny")
        self.assertFalse(expected["isolatedMargin"]["unallocatedCollateralProtectsPositions"])
        self.assertTrue(expected["isolatedMargin"]["allocationRequired"])
        self.assertFalse(expected["runtimeSafety"]["builtInDeadManSwitch"])
        self.assertTrue(
            expected["runtimeSafety"]["heartbeatCancellationRequiredBeforeLive"]
        )
        enabled = json.loads(
            (ROOT / "aftermath-overlay/catalog/enabled.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(enabled["meta"]["enabled_count"], 0)
        self.assertEqual(enabled["packages"], [])


if __name__ == "__main__":
    unittest.main()
