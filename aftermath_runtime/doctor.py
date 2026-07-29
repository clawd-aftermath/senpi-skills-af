"""``doctor`` — the first thing a new operator runs.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

Prints a pass/fail table and exits non-zero on failure.  It validates, in
order: configuration sanity, the API host, market resolution, account
discovery, the active gas mode's own prerequisites, arming state, and the
vendored-skills pin.

Deliberate behaviours:

* **zero markets is a WARN, never a FAIL.**  No markets are live on Aftermath
  before the relaunch; failing on that would make ``doctor`` useless today.
* **the /api/wallet/* family degrades.**  It is published in the spec and 404s
  on the live host (verified 2026-07-28), so a wallet-balance probe that fails
  is reported as a gap, not an outage.
* **no key is ever read.**  The one required secret is a wallet ADDRESS.
  ``doctor`` confirms it parses as a Sui address and stops there.

Run offline (the default) it exercises everything that does not need the
network and clearly marks the rest as skipped, so it is useful in CI too.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .accounts import OWNED_ACCOUNTS_PATH, owned_accounts_request, parse_owned_accounts
from .config import (
    ALLOW_LIVE_READS_ENV,
    API_BASE_URL_ENV,
    ARMED_ENV,
    DEFAULT_API_BASE_URL,
    GAS_MODE_ENV,
    RuntimeConfig,
    WALLET_ADDRESS_ENV,
    assert_not_retired_host,
)
from .errors import AftermathRuntimeError
from .gas import GAS_POOL_PATH, GasConfig, check_gas_mode, gas_pool_request
from .ids import SuiAddress
from .markets import ALL_MARKETS_PATH, MarketCatalog, all_markets_request
from .toolspec import coverage_summary

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    remedy: str | None = None


def _mask(address: str) -> str:
    """Never print a full wallet address into a log or a CI artefact."""
    return f"{address[:6]}…{address[-4:]}" if len(address) > 12 else "…"


def run_checks(
    config: RuntimeConfig,
    *,
    transport: Any | None = None,
) -> list[Check]:
    """Run every preflight check.  ``transport=None`` means offline."""
    checks: list[Check] = []

    # 1. Host.
    try:
        assert_not_retired_host(config.base_url)
        detail = config.base_url
        status = PASS if config.base_url == DEFAULT_API_BASE_URL else WARN
        if status == WARN:
            detail += f" (overridden via {API_BASE_URL_ENV})"
        checks.append(Check("api host", status, detail))
    except AftermathRuntimeError as exc:
        checks.append(
            Check(
                "api host",
                FAIL,
                str(exc),
                f"Unset {API_BASE_URL_ENV} to use {DEFAULT_API_BASE_URL}.",
            )
        )

    # 2. Wallet.  An ADDRESS, never a key.
    if not config.wallet_address:
        checks.append(
            Check(
                "wallet",
                FAIL,
                f"{WALLET_ADDRESS_ENV} is not set",
                f"Set {WALLET_ADDRESS_ENV} to your Sui wallet address. It is "
                "the only value this runtime needs, and it is never a key.",
            )
        )
        wallet: SuiAddress | None = None
    else:
        try:
            wallet = SuiAddress(config.wallet_address)
            checks.append(
                Check("wallet", PASS, f"{_mask(str(wallet))} parses as a Sui address")
            )
        except AftermathRuntimeError as exc:
            wallet = None
            checks.append(
                Check("wallet", FAIL, str(exc), f"Fix {WALLET_ADDRESS_ENV}.")
            )

    # 3. Collateral coin type.
    checks.append(
        Check(
            "collateral",
            PASS,
            config.collateral_coin_type.rsplit("::", 1)[-1]
            + f" ({config.collateral_coin_type[:14]}…)",
        )
    )

    # 4. Gas configuration (structure only; live checks below).
    try:
        gas = GasConfig(
            mode=config.gas_mode,
            budget_mist=config.gas_budget_mist,
            gas_coin_type=config.gas_coin_type,
        )
        checks.append(
            Check(
                "gas config",
                PASS,
                f"mode={gas.mode}, budget={gas.budget_mist} MIST (explicit)"
                + (f", coin={gas.gas_coin_type}" if gas.gas_coin_type else ""),
            )
        )
    except AftermathRuntimeError as exc:
        gas = None
        checks.append(
            Check(
                "gas config",
                FAIL,
                str(exc),
                f"Fix {GAS_MODE_ENV} / AF_GAS_COIN_TYPE / AF_GAS_BUDGET_MIST.",
            )
        )

    # 5. Arming.  Loud, because it is the difference between observing and acting.
    checks.append(
        Check(
            "arming",
            PASS if not config.armed else WARN,
            "DISARMED — nothing will be built, signed, or submitted"
            if not config.armed
            else f"ARMED via {ARMED_ENV}: transactions will be BUILT (still "
            "never signed or submitted by this repository)",
        )
    )

    # 6. Tool coverage.
    summary = coverage_summary()
    checks.append(
        Check(
            "mcp tool coverage",
            PASS,
            ", ".join(f"{count} {status}" for status, count in sorted(summary.items())),
        )
    )

    if transport is None:
        checks.append(
            Check(
                "api reachability",
                SKIP,
                "offline run",
                f"Set {ALLOW_LIVE_READS_ENV}=1 and pass a live transport to "
                "check the API.",
            )
        )
        return checks

    # 7. Markets.  Zero is EXPECTED pre-relaunch.
    catalog: MarketCatalog | None = None
    try:
        payload = transport.post(
            ALL_MARKETS_PATH, all_markets_request(config.collateral_coin_type)
        )
        catalog = MarketCatalog.from_api(
            payload, collateral_coin_type=config.collateral_coin_type
        )
        if catalog.is_empty:
            checks.append(
                Check(
                    "markets",
                    WARN,
                    "0 markets live for this collateral — expected before the "
                    "Aftermath relaunch",
                    "Nothing to fix. Strategies will find nothing to trade "
                    "until markets list.",
                )
            )
        else:
            checks.append(
                Check(
                    "markets",
                    PASS,
                    f"{len(catalog.markets)} live: "
                    + ", ".join(catalog.symbols()[:8])
                    + ("…" if len(catalog.markets) > 8 else ""),
                )
            )
    except AftermathRuntimeError as exc:
        checks.append(
            Check(
                "markets",
                FAIL,
                str(exc),
                f"Verify {API_BASE_URL_ENV} and the collateral coin type.",
            )
        )
    except Exception as exc:  # noqa: BLE001 - transport-level failure
        checks.append(Check("markets", FAIL, f"{ALL_MARKETS_PATH}: {exc}"))

    # 8. Account discovery.
    if wallet is None:
        checks.append(Check("account", SKIP, "no wallet configured"))
    else:
        try:
            payload = transport.post(
                OWNED_ACCOUNTS_PATH, owned_accounts_request(wallet)
            )
            caps = parse_owned_accounts(payload)
            matching = [
                c
                for c in caps
                if c.collateral_coin_type == config.collateral_coin_type
                and not c.is_agent
            ]
            if matching:
                checks.append(
                    Check(
                        "account",
                        PASS,
                        f"{len(matching)} account(s): "
                        + ", ".join(str(c.account_id.value) for c in matching[:5]),
                    )
                )
            else:
                checks.append(
                    Check(
                        "account",
                        WARN,
                        "wallet owns no perpetuals account for this collateral",
                        "Run the composed onboarding PTB (create-account + "
                        "deposit + allocate) to provision one.",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("account", FAIL, f"{OWNED_ACCOUNTS_PATH}: {exc}"))

    # 9. Gas mode prerequisites.
    if gas is not None:
        pool_payload: Mapping[str, Any] | None = None
        pool_error: str | None = None
        if gas.mode == "sponsored" and wallet is not None:
            try:
                pool_payload = transport.post(GAS_POOL_PATH, gas_pool_request(wallet))
            except Exception as exc:  # noqa: BLE001
                pool_error = str(exc)
        result = check_gas_mode(
            gas,
            wallet_address=wallet,
            pool_payload=pool_payload,
            pool_error=pool_error,
        )
        checks.append(
            Check(
                f"gas: {result.mode}",
                PASS if result.ok else FAIL,
                result.detail,
                result.remedy,
            )
        )

    return checks


def render(checks: Sequence[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = ["", "Aftermath V2 preflight", "=" * (width + 46)]
    for check in checks:
        lines.append(f"  {check.status:<4}  {check.name.ljust(width)}  {check.detail}")
        if check.remedy and check.status in (FAIL, WARN):
            lines.append(f"        {' ' * width}  -> {check.remedy}")
    failures = sum(1 for c in checks if c.status == FAIL)
    warnings = sum(1 for c in checks if c.status == WARN)
    lines.append("=" * (width + 46))
    lines.append(
        f"  {len(checks)} checks, {failures} failed, {warnings} warnings"
    )
    lines.append("")
    return "\n".join(lines)


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: Any | None = None,
    write: Callable[[str], None] = lambda text: print(text),
) -> int:
    """Exit code 0 when every check passes or warns; 1 on any failure."""
    try:
        config = RuntimeConfig.from_env(env)
    except AftermathRuntimeError as exc:
        write(f"configuration error: {exc}")
        return 1
    checks = run_checks(config, transport=transport)
    write(render(checks))
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
