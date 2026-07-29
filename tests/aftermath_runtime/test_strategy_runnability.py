"""Every upstream strategy runs through the adapter, unmodified.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

This is the load-bearing test for the whole approach. The claim is not "a
representative subset works" — it is that the pinned upstream corpus, byte for
byte, runs on Aftermath because ONE adapter sits underneath it.

So: discover every ``strategies/**/scan.py``, import it unedited, and run a tick
against both the real adapter (fixture transport) and the mock twin. Zero
network, zero keys, no strategy file changed.

A scanner failing a gate (because Aftermath has no smart-money feed, say) is a
PASS here — that is the strategy correctly declining to trade on data that does
not exist. A scanner crashing is a failure.
"""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aftermath_runtime.adapter import AftermathAdapter  # noqa: E402
from aftermath_runtime.config import RuntimeConfig  # noqa: E402
from aftermath_runtime.harness import (  # noqa: E402
    ScanContext,
    ScanState,
    load_scanner,
    run_scan,
)
from aftermath_runtime.mock import MockAftermathAdapter  # noqa: E402
from aftermath_runtime.transport import AdapterFixtureTransport  # noqa: E402

from test_adapter import COLLATERAL, WALLET, responses  # noqa: E402

INPUTS = {
    "assets": ["BTC", "ETH"],
    "universe": ["BTC", "ETH"],
}


def scanners() -> list[Path]:
    return sorted((ROOT / "strategies").rglob("scan.py"))


def real_adapter() -> AftermathAdapter:
    return AftermathAdapter(
        AdapterFixtureTransport(responses()),
        RuntimeConfig(wallet_address=WALLET, collateral_coin_type=COLLATERAL),
    )


def run_quietly(scan: Path, adapter) -> list[dict]:
    """Scanners log to stderr by contract; keep the test output readable."""
    sink = io.StringIO()
    with contextlib.redirect_stderr(sink), contextlib.redirect_stdout(sink):
        return run_scan(scan, INPUTS, adapter, state=ScanState())


class CorpusDiscoveryTests(unittest.TestCase):
    def test_the_corpus_is_the_full_pinned_set(self):
        found = scanners()
        packages = {path.relative_to(ROOT / "strategies").parts[0] for path in found}
        self.assertEqual(
            len(packages), 99, "expected all 99 upstream strategy packages"
        )
        self.assertEqual(len(found), 125, "expected all 125 scanner instances")

    def test_no_strategy_file_talks_to_the_api_directly(self):
        """The adapter must be the ONLY seam. Grep proves it."""
        offenders: list[str] = []
        for path in (ROOT / "strategies").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for token in ("/api/perpetuals", "/api/ccxt", "aftermath_runtime"):
                    if token in stripped:
                        offenders.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(offenders, [])


class EveryStrategyRunsTests(unittest.TestCase):
    def test_every_scanner_runs_against_the_REAL_adapter(self):
        failures: list[str] = []
        emitted = 0
        for scan in scanners():
            try:
                emitted += len(run_quietly(scan, real_adapter()))
            except Exception as exc:  # noqa: BLE001 - the point of the test
                failures.append(
                    f"{scan.relative_to(ROOT)}: {type(exc).__name__}: {exc}"
                )
        self.assertEqual(failures, [], f"{len(failures)} scanner(s) crashed")
        # At least one strategy must reach the point of emitting, otherwise the
        # corpus is passing only because everything short-circuits.
        self.assertGreater(emitted, 0)

    def test_every_scanner_runs_against_the_MOCK_with_no_network_and_no_keys(self):
        failures: list[str] = []
        emitted = 0
        for scan in scanners():
            try:
                emitted += len(run_quietly(scan, MockAftermathAdapter()))
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    f"{scan.relative_to(ROOT)}: {type(exc).__name__}: {exc}"
                )
        self.assertEqual(failures, [], f"{len(failures)} scanner(s) crashed")
        self.assertGreater(emitted, 0)

    def test_no_scanner_placed_an_order(self):
        """Scanners are read-only by contract; prove no build route was touched."""
        for scan in scanners():
            transport = AdapterFixtureTransport(responses())
            adapter = AftermathAdapter(
                transport,
                RuntimeConfig(wallet_address=WALLET, collateral_coin_type=COLLATERAL),
            )
            sink = io.StringIO()
            with contextlib.redirect_stderr(sink), contextlib.redirect_stdout(sink):
                run_scan(scan, INPUTS, adapter, state=ScanState())
            builds = [
                path
                for path, _ in transport.calls
                if "/transactions/" in path or "submit" in path
            ]
            self.assertEqual(builds, [], f"{scan.relative_to(ROOT)} built a tx")


class ScannerIsolationTests(unittest.TestCase):
    def test_each_package_gets_its_OWN_scoring_module(self):
        """Two packages ship different ``scoring.py`` under the same name.

        Leaving the first cached would hand the second the wrong maths and look
        like a successful import.
        """
        paths = [
            path
            for path in scanners()
            if (path.parent / "scoring.py").is_file()
        ]
        self.assertGreater(len(paths), 2)
        pre_existing = sys.modules.get("scoring")

        first = load_scanner(paths[0])
        second = load_scanner(paths[1])
        self.assertIsNot(first, second)
        self.assertIsNot(
            getattr(first, "scoring", first),
            getattr(second, "scoring", second),
            "both scanners share one scoring module -- the cached first "
            "package's maths would silently run the second package's strategy",
        )
        for module, path in ((first, paths[0]), (second, paths[1])):
            scoring = getattr(module, "scoring", None)
            if scoring is not None:
                self.assertEqual(
                    Path(scoring.__file__).resolve().parent, path.parent
                )
        # Loading left nothing new cached under the bare name.
        self.assertIs(sys.modules.get("scoring"), pre_existing)


class ScanContextTests(unittest.TestCase):
    def test_the_context_matches_the_upstream_scan_contract(self):
        context = ScanContext(senpi_mcp=MockAftermathAdapter(), wallet=WALLET)
        self.assertTrue(hasattr(context.senpi_mcp, "call_tool"))
        self.assertEqual(context.wallet, WALLET)
        self.assertEqual(context.scanner_name, "aftermath")
        self.assertIsNone(context.get("missing"))
        with self.assertRaises(Exception):
            context.wallet = "0xdead"  # type: ignore[misc]

    def test_state_commits_only_on_a_clean_tick(self):
        state = ScanState()
        state.append({"a": 1})
        self.assertEqual(len(state), 1)
        state.rollback()
        self.assertEqual(len(state), 0)
        state.append({"a": 1})
        state.commit()
        self.assertEqual(state.last(), {"a": 1})

    def test_state_rolls_back_when_a_scan_raises(self, ):
        state = ScanState()
        module = ROOT / "tests" / "aftermath_runtime" / "fixtures" / "raising_scan.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text(
            "def scan(inputs, ctx):\n"
            "    ctx.state.append({'staged': True})\n"
            "    raise RuntimeError('boom')\n",
            encoding="utf-8",
        )
        try:
            with self.assertRaises(RuntimeError):
                run_scan(module, {}, MockAftermathAdapter(), state=state)
            self.assertEqual(len(state), 0)
        finally:
            module.unlink()

    def test_state_is_bounded(self):
        state = ScanState(max_count=3)
        for index in range(10):
            state.append({"i": index})
            state.commit()
        self.assertEqual(len(state), 3)
        self.assertEqual(state.last(), {"i": 9})

    def test_append_requires_a_dict(self):
        with self.assertRaises(TypeError):
            ScanState().append(["not", "a", "dict"])  # type: ignore[arg-type]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
