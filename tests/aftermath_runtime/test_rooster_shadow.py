# Copyright 2026 Senpi (https://senpi.ai) — Apache-2.0
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aftermath_runtime import AftermathVenue, FixtureTransport

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
SCANNERS = (
    ROOT
    / "aftermath-overlay"
    / "shadow"
    / "strategies"
    / "rooster"
    / "main"
    / "scanners"
)


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_scan():
    sys.path.insert(0, str(SCANNERS))
    try:
        sys.modules.pop("scoring", None)
        spec = importlib.util.spec_from_file_location(
            "aftermath_rooster_scan", SCANNERS / "scan.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class MemoryState:
    def __init__(self):
        self.rows = []

    def __len__(self):
        return len(self.rows)

    def last(self):
        return self.rows[-1] if self.rows else None

    def append(self, row):
        self.rows.append(row)


def candle_payload(resolution: str, end_ms: int):
    if resolution == "4h":
        values = [99, 99.2, 99.4, 99.6, 99.8, 100, 100.2, 100.4]
        interval = 4 * 60 * 60 * 1000
        volumes = [1000] * len(values)
    else:
        values = [100 + i * 0.001 for i in range(30)] + [100.2, 100.5, 100.9]
        interval = 15 * 60 * 1000
        volumes = [1000] * 30 + [2500, 2800, 3100]
    start = end_ms - len(values) * interval
    return {
        "candles": [
            {
                "timestamp": start + index * interval,
                "open": price,
                "high": price * 1.001,
                "low": price * 0.999,
                "close": price,
                "volume": volumes[index],
            }
            for index, price in enumerate(values)
        ]
    }


class RoosterAftermathGoldenTests(unittest.TestCase):
    def test_shadow_scan_preserves_upstream_signal_math_without_writes(self):
        markets = fixture("markets.json")
        account = fixture("accounts_positions.json")
        account["accounts"][0]["positions"] = []

        def candles(_path, payload):
            return candle_payload(payload["resolution"], payload["toTimestamp"])

        transport = FixtureTransport(
            {
                "/api/perpetuals/markets": markets,
                "/api/perpetuals/accounts/positions": account,
                "/api/perpetuals/market/candle-history": candles,
            }
        )
        state = MemoryState()
        context = SimpleNamespace(
            venue=AftermathVenue(transport), account_id=7, state=state
        )
        scanner = load_scan()
        # 2026-07-28 13:00:00 UTC: 30 minutes before the 13:30 open.
        now = 1_785_243_600.0
        inputs = {
            "assets": ["BTC"],
            "sessionOpensUtc": ["13:30"],
            "preOpenMinutes": 45,
            "minScore": 5,
        }
        with patch.object(scanner.time, "time", return_value=now):
            signals = scanner.scan(inputs, context)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["asset"], "BTC")
        self.assertEqual(signals[0]["direction"], "LONG")
        self.assertGreaterEqual(signals[0]["data"]["score"], 5)
        self.assertEqual(state.rows[-1]["result"]["mode"], "shadow")
        paths = [path for path, _ in transport.calls]
        self.assertEqual(
            paths,
            [
                "/api/perpetuals/accounts/positions",
                "/api/perpetuals/markets",
                "/api/perpetuals/market/candle-history",
                "/api/perpetuals/market/candle-history",
            ],
        )
        self.assertTrue(all("transaction" not in path for path in paths))

    def test_clock_gate_makes_zero_venue_reads_outside_window(self):
        transport = FixtureTransport({})
        context = SimpleNamespace(
            venue=AftermathVenue(transport), account_id=7, state=MemoryState()
        )
        scanner = load_scan()
        with patch.object(scanner.time, "time", return_value=1_785_210_000.0):
            signals = scanner.scan(
                {"sessionOpensUtc": ["13:30"], "preOpenMinutes": 45}, context
            )
        self.assertEqual(signals, [])
        self.assertEqual(transport.calls, [])

    def test_unknown_position_market_blocks_instead_of_allowing_duplicate_entry(self):
        account = fixture("accounts_positions.json")
        account["accounts"][0]["positions"][0]["marketId"] = "missing-market"
        transport = FixtureTransport(
            {
                "/api/perpetuals/accounts/positions": account,
                "/api/perpetuals/markets": fixture("markets.json"),
            }
        )
        context = SimpleNamespace(
            venue=AftermathVenue(transport), account_id=7, state=MemoryState()
        )
        scanner = load_scan()
        with patch.object(scanner.time, "time", return_value=1_785_243_600.0):
            signals = scanner.scan(
                {
                    "assets": ["BTC"],
                    "sessionOpensUtc": ["13:30"],
                    "preOpenMinutes": 45,
                },
                context,
            )
        self.assertEqual(signals, [])
        self.assertEqual(
            [path for path, _ in transport.calls],
            ["/api/perpetuals/accounts/positions", "/api/perpetuals/markets"],
        )
        self.assertEqual(
            context.state.rows[-1]["result"]["skipReason"],
            "position_market_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
