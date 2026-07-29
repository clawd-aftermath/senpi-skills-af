"""Single source of configuration for the Aftermath V2 runtime.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

Every host, every mode, every safety flag resolves from here.  In particular
the API host is defined EXACTLY ONCE (``DEFAULT_API_BASE_URL``) and every call
site reads it from this module.  The relaunch domain is expected to change; a
tree with the hostname smeared across forty files breaks on that day.

Two traps this module exists to neutralise:

* The vendored skills at ``AFTERMATH_SKILLS_REF/`` name the RETIRED v1 host in
  22 places, and the live OpenAPI document's own ``servers`` block still lists
  it as the "Production server".  Both are wrong.  Take their patterns, never
  their URLs.
* ``https://v2-preview.aftermath.finance`` is production mainnet despite the
  hostname.  It is not a testbed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import ConfigError

# ── The one host constant ────────────────────────────────────────
# Overridable by AF_API_BASE_URL without touching source.  Nothing else in the
# tree may contain a hostname.
DEFAULT_API_BASE_URL = "https://v2-preview.aftermath.finance"
API_BASE_URL_ENV = "AF_API_BASE_URL"

# The retired host, expressed in pieces so this file itself never contains a
# usable v1 URL and so the CI host-grep does not flag its own guard rail.
_RETIRED_HOST_SUFFIX = "aftermath" ".finance"
_LIVE_HOST_PREFIX = "v2-preview."


def api_base_url(env: Mapping[str, str] | None = None) -> str:
    """Resolve the API base URL from the single config constant."""
    source = os.environ if env is None else env
    raw = (source.get(API_BASE_URL_ENV) or "").strip() or DEFAULT_API_BASE_URL
    return raw.rstrip("/")


def assert_not_retired_host(url: str) -> None:
    """Fail closed on the dead v1 API host.

    A wrong host that silently returns stale data is the single most expensive
    bug class this integration has produced.
    """
    host = url.split("://", 1)[-1].split("/", 1)[0].lower()
    if host.endswith(_RETIRED_HOST_SUFFIX) and not host.startswith(_LIVE_HOST_PREFIX):
        raise ConfigError(
            f"{url!r} points at the retired v1 API host. "
            f"The live host is {DEFAULT_API_BASE_URL}."
        )


# ── Turnkey environment variables ────────────────────────────────
# Exactly one secret is required of the operator: their wallet.  Everything
# else has a competent default.

WALLET_ADDRESS_ENV = "AF_WALLET_ADDRESS"
"""The ONE required variable: the operator's Sui wallet address.

A wallet ADDRESS, never a key.  This runtime never reads, requests, derives or
stores a private key; signing is delegated to a caller-supplied callback that
ships unwired.
"""

GAS_MODE_ENV = "AF_GAS_MODE"
GAS_COIN_TYPE_ENV = "AF_GAS_COIN_TYPE"
GAS_BUDGET_ENV = "AF_GAS_BUDGET_MIST"
COLLATERAL_COIN_TYPE_ENV = "AF_COLLATERAL_COIN_TYPE"
ACCOUNT_ID_ENV = "AF_ACCOUNT_ID"
ARMED_ENV = "AF_ARMED"
ALLOW_LIVE_READS_ENV = "AFTERMATH_ALLOW_LIVE_READS"
ALLOW_TX_BUILD_ENV = "AFTERMATH_ALLOW_TX_BUILD"

# USDC on Sui mainnet is the default perpetuals collateral.  Overridable, and
# `doctor` validates that markets actually exist for whatever is configured.
DEFAULT_COLLATERAL_COIN_TYPE = (
    "0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7"
    "::usdc::USDC"
)

SUI_COIN_TYPE = "0x2::sui::SUI"


def _env_flag(source: Mapping[str, str], name: str) -> bool:
    return (source.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved, validated runtime configuration.

    ``armed`` is the single documented flag that turns a strategy from
    observe-only into something that would produce a signature.  It defaults to
    False and this repository ships with no signer wired up at all, so an armed
    runtime still cannot broadcast.
    """

    base_url: str = DEFAULT_API_BASE_URL
    wallet_address: str | None = None
    collateral_coin_type: str = DEFAULT_COLLATERAL_COIN_TYPE
    account_id: int | None = None
    gas_mode: str = "sponsored"
    gas_coin_type: str | None = None
    gas_budget_mist: int = 50_000_000
    armed: bool = False
    allow_live_reads: bool = False
    allow_tx_build: bool = False
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        assert_not_retired_host(self.base_url)
        if self.gas_budget_mist <= 0:
            raise ConfigError("gas budget must be a positive number of MIST")

    @property
    def venue_runtime_config(self) -> dict[str, str]:
        """The read-only venue gate config understood by ``gate.py``."""
        return {"mode": "shadow", "write_policy": "deny"}

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RuntimeConfig":
        source = dict(os.environ if env is None else env)
        wallet = (source.get(WALLET_ADDRESS_ENV) or "").strip() or None
        account_raw = (source.get(ACCOUNT_ID_ENV) or "").strip()
        account_id: int | None = None
        if account_raw:
            digits = account_raw[:-1] if account_raw.endswith("n") else account_raw
            if not digits.isdigit():
                raise ConfigError(
                    f"{ACCOUNT_ID_ENV} must be a non-negative integer "
                    f'(optionally "n"-suffixed), got {account_raw!r}'
                )
            account_id = int(digits)
        budget_raw = (source.get(GAS_BUDGET_ENV) or "").strip()
        if budget_raw and not budget_raw.isdigit():
            raise ConfigError(f"{GAS_BUDGET_ENV} must be a positive integer of MIST")
        return cls(
            base_url=api_base_url(source),
            wallet_address=wallet,
            collateral_coin_type=(
                (source.get(COLLATERAL_COIN_TYPE_ENV) or "").strip()
                or DEFAULT_COLLATERAL_COIN_TYPE
            ),
            account_id=account_id,
            gas_mode=(source.get(GAS_MODE_ENV) or "").strip().lower() or "sponsored",
            gas_coin_type=(source.get(GAS_COIN_TYPE_ENV) or "").strip() or None,
            gas_budget_mist=int(budget_raw) if budget_raw else 50_000_000,
            armed=_env_flag(source, ARMED_ENV),
            allow_live_reads=_env_flag(source, ALLOW_LIVE_READS_ENV),
            allow_tx_build=_env_flag(source, ALLOW_TX_BUILD_ENV),
        )
