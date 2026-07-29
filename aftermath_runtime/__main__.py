"""CLI entry point: ``python3 -m aftermath_runtime <command>``.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

Commands:

``doctor``     preflight table; exits non-zero on failure.  Offline by default;
               pass ``--live`` to check the API, which additionally requires
               ``AFTERMATH_ALLOW_LIVE_READS=1`` so no command can open a socket
               by accident.
``coverage``   the MCP tool coverage table.
``config``     the resolved configuration, with the wallet address masked.

Nothing here signs, submits, or broadcasts, and nothing reads a private key.
"""

from __future__ import annotations

import os
import sys
from typing import Sequence

from . import doctor as doctor_module
from .config import RuntimeConfig
from .errors import AftermathRuntimeError
from .toolspec import coverage_table

USAGE = """usage: python3 -m aftermath_runtime <command>

  doctor [--live]   preflight checks; non-zero exit on failure
  coverage          MCP tool coverage table
  config            resolved configuration (wallet address masked)
"""


def _live_transport(config: RuntimeConfig):
    from .transport import UrllibAdapterTransport

    return UrllibAdapterTransport(
        base_url=config.base_url,
        allow_network=True,
        allow_builds=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(USAGE)
        return 0

    command, *rest = args

    if command == "coverage":
        print(coverage_table())
        return 0

    if command == "config":
        try:
            config = RuntimeConfig.from_env()
        except AftermathRuntimeError as exc:
            print(f"configuration error: {exc}", file=sys.stderr)
            return 1
        wallet = config.wallet_address
        masked = f"{wallet[:6]}…{wallet[-4:]}" if wallet else "(unset)"
        print(f"  api host      {config.base_url}")
        print(f"  wallet        {masked}")
        print(f"  collateral    {config.collateral_coin_type}")
        print(f"  account       {config.account_id if config.account_id else 'auto'}")
        print(f"  gas mode      {config.gas_mode}")
        print(f"  gas budget    {config.gas_budget_mist} MIST (explicit)")
        print(f"  gas coin      {config.gas_coin_type or '(n/a)'}")
        print(f"  armed         {'YES' if config.armed else 'no'}")
        return 0

    if command == "doctor":
        live = "--live" in rest
        transport = None
        if live:
            if os.environ.get("AFTERMATH_ALLOW_LIVE_READS") != "1":
                print(
                    "doctor --live requires AFTERMATH_ALLOW_LIVE_READS=1",
                    file=sys.stderr,
                )
                return 1
            try:
                transport = _live_transport(RuntimeConfig.from_env())
            except AftermathRuntimeError as exc:
                print(f"cannot open a live transport: {exc}", file=sys.stderr)
                return 1
        return doctor_module.main(transport=transport)

    print(f"unknown command: {command}\n\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
