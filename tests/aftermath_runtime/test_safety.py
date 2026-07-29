"""Margin health, sizing, circuit breakers, kill switch, serialisation.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aftermath_runtime.errors import (  # noqa: E402
    CircuitBreakerTripped,
    NormalizationError,
)
from aftermath_runtime.safety import (  # noqa: E402
    DANGER,
    LIQUIDATION,
    SAFE,
    WARNING,
    BotState,
    CircuitBreaker,
    HardLimits,
    KillSwitch,
    SerialGate,
    ShutdownHandler,
    SoftLimits,
    assess_margin_health,
    check_soft_limits,
    collateral_for_notional,
    enforce_hard_limits,
    max_size_for_risk,
)


class MarginHealthTests(unittest.TestCase):
    def test_every_zone_boundary(self):
        # Binary-exact values, so a boundary case tests the boundary and not
        # floating-point rounding.
        maintenance = 0.5
        cases = [
            (0.25, LIQUIDATION),  # 0.5x
            (0.5, DANGER),  # 1.0x
            (0.625, DANGER),  # 1.25x
            (0.75, WARNING),  # 1.5x
            (0.875, WARNING),  # 1.75x
            (1.0, SAFE),  # 2.0x
            (4.0, SAFE),  # 8.0x
        ]
        for ratio, expected in cases:
            with self.subTest(ratio=ratio):
                self.assertEqual(
                    assess_margin_health(ratio, maintenance).zone, expected
                )

    def test_buffer_multiple_is_reported(self):
        health = assess_margin_health(0.10, 0.05)
        self.assertAlmostEqual(health.buffer_multiple, 2.0)

    def test_missing_or_nonsense_data_refuses_to_guess(self):
        for ratio, maintenance in (
            (None, 0.05),
            (0.1, 0),
            (0.1, -1),
            (float("nan"), 0.05),
            (float("inf"), 0.05),
            ("0.1", 0.05),
        ):
            with self.subTest(ratio=ratio, maintenance=maintenance):
                with self.assertRaises(NormalizationError):
                    assess_margin_health(ratio, maintenance)  # type: ignore[arg-type]


class SizingTests(unittest.TestCase):
    def test_two_percent_rule(self):
        # $10,000 collateral, 2% risk, $100 stop distance -> 2 units.
        self.assertAlmostEqual(max_size_for_risk(10_000, 1_000, 900), 2.0)

    def test_degenerate_inputs_raise(self):
        with self.assertRaises(NormalizationError):
            max_size_for_risk(0, 100, 90)
        with self.assertRaises(NormalizationError):
            max_size_for_risk(100, 100, 100)
        with self.assertRaises(NormalizationError):
            max_size_for_risk(100, 100, 90, risk_percent=0)

    def test_percent_sizing_translates_to_explicit_collateral(self):
        # The Aftermath model: an explicit collateral amount, not a marginPct.
        self.assertAlmostEqual(collateral_for_notional(10_000, 5), 2_000.0)
        with self.assertRaises(NormalizationError):
            collateral_for_notional(10_000, 0)


class CircuitBreakerTests(unittest.TestCase):
    def test_soft_limits_warn_without_halting(self):
        warnings = check_soft_limits(
            SoftLimits(),
            BotState(
                drawdown_pct=9.0,
                position_notional=60_000,
                effective_leverage=9,
                margin_buffer=1.0,
            ),
        )
        self.assertEqual(len(warnings), 4)

    def test_hard_limits_halt(self):
        limits = HardLimits()
        self.assertIsNone(enforce_hard_limits(limits, BotState()))
        self.assertIn(
            "drawdown",
            enforce_hard_limits(limits, BotState(drawdown_pct=20.0)) or "",
        )
        self.assertIn(
            "daily loss",
            enforce_hard_limits(limits, BotState(daily_loss=10_000)) or "",
        )
        self.assertIn(
            "trade count",
            enforce_hard_limits(limits, BotState(daily_trade_count=1_000)) or "",
        )

    def test_the_halt_latches_and_blocks_trading(self):
        logs: list[str] = []
        breaker = CircuitBreaker(log=logs.append)
        breaker.evaluate(BotState(drawdown_pct=99.0))
        self.assertTrue(breaker.halted)
        with self.assertRaises(CircuitBreakerTripped):
            breaker.assert_can_trade()
        # A recovered metric must NOT silently re-arm the strategy.
        breaker.evaluate(BotState(drawdown_pct=0.0))
        self.assertTrue(breaker.halted)
        breaker.reset()
        breaker.assert_can_trade()

    def test_both_tiers_are_exercised_by_one_evaluate_call(self):
        logs: list[str] = []
        breaker = CircuitBreaker(log=logs.append)
        breaker.evaluate(BotState(drawdown_pct=20.0))
        self.assertTrue(any("soft limit" in line for line in logs))
        self.assertTrue(any("HALT" in line for line in logs))


class KillSwitchTests(unittest.TestCase):
    def test_it_fires_only_after_the_silence_window(self):
        now = [0.0]
        switch = KillSwitch(10.0, cancel_all=lambda: [], clock=lambda: now[0])
        self.assertFalse(switch.check())
        now[0] = 9.0
        self.assertFalse(switch.check())
        now[0] = 11.0
        self.assertTrue(switch.check())
        self.assertTrue(switch.fired)
        self.assertTrue(switch.verified)

    def test_a_heartbeat_resets_the_window(self):
        now = [0.0]
        switch = KillSwitch(10.0, cancel_all=lambda: [], clock=lambda: now[0])
        now[0] = 9.0
        switch.heartbeat()
        now[0] = 15.0
        self.assertFalse(switch.check())

    def test_cancellation_is_VERIFIED_not_assumed(self):
        survivors = [{"id": "1"}]
        logs: list[str] = []
        switch = KillSwitch(1.0, cancel_all=lambda: survivors, log=logs.append)
        with self.assertRaisesRegex(CircuitBreakerTripped, "survived"):
            switch.trigger("test")
        self.assertFalse(switch.verified)
        # Still armed: the exposure is real and a later attempt must fire.
        self.assertTrue(switch.armed)
        self.assertTrue(any("NOT verified" in line for line in logs))

    def test_a_verified_cancellation_disarms(self):
        switch = KillSwitch(1.0, cancel_all=lambda: [])
        switch.trigger("test")
        self.assertTrue(switch.verified)
        self.assertFalse(switch.armed)
        # A disarmed switch does not re-cancel.
        switch.trigger("again")

    def test_rearm_clears_state(self):
        switch = KillSwitch(1.0, cancel_all=lambda: [])
        switch.trigger("test")
        switch.rearm()
        self.assertTrue(switch.armed)
        self.assertFalse(switch.fired)


class ShutdownTests(unittest.TestCase):
    def test_clean_shutdown_exits_zero(self):
        handler = ShutdownHandler(KillSwitch(1.0, cancel_all=lambda: []))
        self.assertEqual(handler.handle("SIGINT"), 0)
        self.assertEqual(handler.handled, ["SIGINT"])

    def test_failed_cancellation_exits_non_zero(self):
        logs: list[str] = []
        handler = ShutdownHandler(
            KillSwitch(1.0, cancel_all=lambda: [{"id": "1"}]), log=logs.append
        )
        self.assertEqual(handler.handle("SIGTERM"), 1)
        self.assertTrue(any("FAILED" in line for line in logs))


class SerialGateTests(unittest.TestCase):
    def test_reentrancy_is_refused_rather_than_queued(self):
        gate = SerialGate()
        with gate:
            with self.assertRaisesRegex(CircuitBreakerTripped, "concurrent"):
                with gate:
                    pass

    def test_the_gate_reopens_after_use(self):
        gate = SerialGate()
        with gate:
            pass
        with gate:
            pass


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
