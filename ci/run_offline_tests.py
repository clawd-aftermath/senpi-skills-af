#!/usr/bin/env python3
"""Run every downstream test with process-wide network denial.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
import sys
import unittest
from unittest import mock  # noqa: F401 - load asyncio/ssl before socket denial


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def deny_network(*_args, **_kwargs):
    raise AssertionError("network access is forbidden in downstream tests")


def main() -> int:
    os.environ["AFTERMATH_OFFLINE_TESTS"] = "1"
    socket.socket = deny_network
    socket.create_connection = deny_network

    loader = unittest.TestLoader()
    suite = unittest.TestSuite(
        (
            loader.discover(
                str(ROOT / "tests" / "aftermath_runtime"),
                pattern="test_*.py",
                top_level_dir=str(ROOT / "tests" / "aftermath_runtime"),
            ),
            loader.discover(
                str(ROOT / "tests"),
                pattern="test_*.py",
                top_level_dir=str(ROOT / "tests"),
            ),
        )
    )
    print("offline network guard active", file=sys.stderr)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
