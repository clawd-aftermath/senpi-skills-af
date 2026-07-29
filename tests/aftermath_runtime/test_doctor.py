"""``doctor`` preflight: the table, the exit code, and the degradations.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aftermath_runtime import doctor  # noqa: E402
from aftermath_runtime.config import RuntimeConfig  # noqa: E402
from aftermath_runtime.transport import AdapterFixtureTransport  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_adapter import COLLATERAL, WALLET, responses  # noqa: E402


def statuses(checks) -> dict[str, str]:
    return {check.name: check.status for check in checks}


class OfflineDoctorTests(unittest.TestCase):
    def test_it_passes_offline_with_a_wallet_and_skips_the_network(self):
        config = RuntimeConfig(wallet_address=WALLET)
        checks = doctor.run_checks(config)
        table = statuses(checks)
        self.assertEqual(table["api host"], doctor.PASS)
        self.assertEqual(table["wallet"], doctor.PASS)
        self.assertEqual(table["gas config"], doctor.PASS)
        self.assertEqual(table["api reachability"], doctor.SKIP)

    def test_a_missing_wallet_is_the_one_fatal_configuration_gap(self):
        checks = doctor.run_checks(RuntimeConfig())
        self.assertEqual(statuses(checks)["wallet"], doctor.FAIL)
        remedy = next(c.remedy for c in checks if c.name == "wallet")
        self.assertIn("AF_WALLET_ADDRESS", remedy)
        self.assertIn("never a key", remedy)

    def test_the_wallet_address_is_masked_in_the_output(self):
        checks = doctor.run_checks(RuntimeConfig(wallet_address=WALLET))
        detail = next(c.detail for c in checks if c.name == "wallet")
        self.assertNotIn(WALLET, detail)
        self.assertIn("…", detail)

    def test_a_retired_host_fails(self):
        env = {"AF_WALLET_ADDRESS": WALLET, "AF_API_BASE_URL": "https://aftermath" + ".finance"}
        lines: list[str] = []
        self.assertEqual(doctor.main(env=env, write=lines.append), 1)

    def test_disarmed_is_reported_as_a_pass_and_armed_as_a_warning(self):
        disarmed = statuses(doctor.run_checks(RuntimeConfig(wallet_address=WALLET)))
        self.assertEqual(disarmed["arming"], doctor.PASS)
        armed = doctor.run_checks(RuntimeConfig(wallet_address=WALLET, armed=True))
        self.assertEqual(statuses(armed)["arming"], doctor.WARN)
        self.assertIn(
            "never signed", next(c.detail for c in armed if c.name == "arming")
        )

    def test_dynamic_gas_without_a_chosen_coin_fails_the_config_check(self):
        checks = doctor.run_checks(
            RuntimeConfig(wallet_address=WALLET, gas_mode="dynamic")
        )
        self.assertEqual(statuses(checks)["gas config"], doctor.FAIL)

    def test_exit_code_is_zero_when_nothing_failed(self):
        lines: list[str] = []
        code = doctor.main(env={"AF_WALLET_ADDRESS": WALLET}, write=lines.append)
        self.assertEqual(code, 0)
        self.assertIn("Aftermath V2 preflight", "\n".join(lines))

    def test_exit_code_is_one_when_something_failed(self):
        lines: list[str] = []
        self.assertEqual(doctor.main(env={}, write=lines.append), 1)
        self.assertIn("0 failed", "\n".join(lines).replace("1 failed", "0 failed"))


class LiveDoctorTests(unittest.TestCase):
    def transport(self, **overrides):
        return AdapterFixtureTransport(responses(**overrides))

    def config(self, **kwargs) -> RuntimeConfig:
        base = dict(wallet_address=WALLET, collateral_coin_type=COLLATERAL)
        base.update(kwargs)
        return RuntimeConfig(**base)  # type: ignore[arg-type]

    def test_a_healthy_environment_passes_every_check(self):
        checks = doctor.run_checks(self.config(), transport=self.transport())
        table = statuses(checks)
        self.assertEqual(table["markets"], doctor.PASS)
        self.assertEqual(table["account"], doctor.PASS)
        self.assertEqual(table["gas: sponsored"], doctor.PASS)
        self.assertFalse([c for c in checks if c.status == doctor.FAIL])

    def test_zero_markets_WARNS_and_never_fails(self):
        checks = doctor.run_checks(
            self.config(),
            transport=self.transport(**{"/api/perpetuals/all-markets": {"markets": []}}),
        )
        markets = next(c for c in checks if c.name == "markets")
        self.assertEqual(markets.status, doctor.WARN)
        self.assertIn("expected before the Aftermath relaunch", markets.detail)
        self.assertFalse([c for c in checks if c.status == doctor.FAIL])

    def test_no_account_WARNS_and_points_at_the_onboarding_ptb(self):
        checks = doctor.run_checks(
            self.config(),
            transport=self.transport(
                **{"/api/perpetuals/accounts/owned": {"accountCaps": []}}
            ),
        )
        account = next(c for c in checks if c.name == "account")
        self.assertEqual(account.status, doctor.WARN)
        self.assertIn("create-account + deposit + allocate", account.remedy or "")

    def test_an_unreachable_gas_pool_fails_the_sponsored_check_actionably(self):
        transport = self.transport()
        del transport.responses["/api/gas-pool/pool"]  # type: ignore[union-attr]
        checks = doctor.run_checks(self.config(), transport=transport)
        gas = next(c for c in checks if c.name.startswith("gas:"))
        self.assertEqual(gas.status, doctor.FAIL)
        self.assertIn("AF_GAS_MODE=self", gas.remedy or "")

    def test_self_gas_does_not_call_the_pool_at_all(self):
        transport = self.transport()
        doctor.run_checks(self.config(gas_mode="self"), transport=transport)
        self.assertNotIn(
            "/api/gas-pool/pool", [path for path, _ in transport.calls]
        )

    def test_the_rendered_table_shows_remedies_for_failures(self):
        checks = doctor.run_checks(RuntimeConfig())
        text = doctor.render(checks)
        self.assertIn("FAIL", text)
        self.assertIn("->", text)
        self.assertIn("checks,", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
