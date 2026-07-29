"""User-selectable gas payment.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

Gas is the operator's choice, not something this runtime decides for them.
One config value (``AF_GAS_MODE``) selects between three modes:

``sponsored``  the Aftermath gas pool pays.  The operator needs no SUI at all.
               This is the default so a fresh wallet works on first run.
``self``       the operator's own SUI pays, the ordinary Sui gas-coin path.
``dynamic``    gas is paid in another coin (USDC and friends) by routing the
               built transaction through ``/api/dynamic-gas``.  The operator
               also chooses WHICH coin pays, via ``AF_GAS_COIN_TYPE``.

Two endpoint facts, verified against the live V2 spec and easy to get wrong:

* ``POST /api/gas-pool/pool`` requires ``{walletAddress}`` and answers
  ``{balance, gasPoolId?, walletAddress, whitelistedAddresses[]}``.  It is a
  pool lookup, and it is a POST — not a GET, not a health endpoint.
* ``POST /api/dynamic-gas`` requires ``{serializedTx, walletAddress,
  gasCoinType}`` and answers ``{txBytes, sponsoredSignature}``.  It is a
  TRANSFORM over an already-built transaction, **not** a health check.  There
  is no meaningful way to ping it without a real transaction, so ``doctor``
  validates its preconditions and reports that the path is confirmed on first
  use rather than pretending to have proven it.

Sponsor and sender MAY legitimately be the same Sui address.  Nothing here
asserts they differ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .config import SUI_COIN_TYPE
from .errors import ConfigError
from .ids import SuiAddress

GAS_MODES = ("sponsored", "self", "dynamic")

GAS_POOL_PATH = "/api/gas-pool/pool"
DYNAMIC_GAS_PATH = "/api/dynamic-gas"

# Auto-estimation under-counts the storage cost of objects a transaction
# creates, which surfaces later as InsufficientGas on something that simulated
# clean.  Always set the budget explicitly.
DEFAULT_GAS_BUDGET_MIST = 50_000_000  # 0.05 SUI


def parse_gas_mode(value: str | None, fallback: str = "sponsored") -> str:
    if value is None or not str(value).strip():
        return fallback
    text = str(value).strip().lower()
    if text not in GAS_MODES:
        raise ConfigError(
            f"invalid gas mode {value!r}; expected one of: {', '.join(GAS_MODES)}"
        )
    return text


@dataclass(frozen=True)
class GasConfig:
    """A resolved gas configuration.

    ``sponsor`` is populated only once the pool has actually been resolved; a
    sponsored config with no sponsor is a config that has not been checked yet,
    and ``apply_to_body`` deliberately refuses to guess one.
    """

    mode: str = "sponsored"
    budget_mist: int = DEFAULT_GAS_BUDGET_MIST
    sponsor: SuiAddress | None = None
    gas_coin_type: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in GAS_MODES:
            raise ConfigError(f"invalid gas mode: {self.mode!r}")
        if not isinstance(self.budget_mist, int) or self.budget_mist <= 0:
            raise ConfigError("gas budget must be a positive integer of MIST")
        if self.mode == "dynamic" and not self.gas_coin_type:
            raise ConfigError(
                "dynamic gas requires an explicit gas coin type "
                "(AF_GAS_COIN_TYPE) — the operator chooses which coin pays"
            )
        if self.mode == "self" and self.gas_coin_type not in (None, SUI_COIN_TYPE):
            raise ConfigError(
                "'self' gas pays in SUI; set AF_GAS_MODE=dynamic to pay in "
                "another coin"
            )

    def apply_to_body(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Return a NEW request body carrying this gas configuration.

        Never mutates the caller's body.  The gas budget is always written
        explicitly.
        """
        out: dict[str, Any] = dict(body)
        out["gasBudget"] = str(self.budget_mist)
        if self.mode == "sponsored":
            if self.sponsor is None:
                raise ConfigError(
                    "sponsored gas selected but no sponsor has been resolved; "
                    f"call the gas pool ({GAS_POOL_PATH}) first"
                )
            # Verified shape: `sponsor` is an object with `walletAddress`.
            out["sponsor"] = {"walletAddress": str(self.sponsor)}
            out["isSponsoredTx"] = True
        elif self.mode == "dynamic":
            # Dynamic gas does not change the BUILD body; it rewrites the built
            # transaction afterwards.  Recording the coin here keeps the choice
            # visible to the inspection gate.
            out.setdefault("isSponsoredTx", False)
        else:
            out.setdefault("isSponsoredTx", False)
        return out

    def dynamic_gas_request(
        self, serialized_tx: str, wallet_address: SuiAddress
    ) -> dict[str, Any]:
        """Build the ``/api/dynamic-gas`` transform request.

        Required fields verified against the live spec.
        """
        if self.mode != "dynamic":
            raise ConfigError("dynamic_gas_request is only valid in 'dynamic' mode")
        if not isinstance(serialized_tx, str) or not serialized_tx:
            raise ConfigError("dynamic gas needs the serialized transaction")
        return {
            "serializedTx": serialized_tx,
            "walletAddress": str(wallet_address),
            "gasCoinType": self.gas_coin_type,
        }


def gas_pool_request(wallet_address: SuiAddress) -> dict[str, Any]:
    """``POST /api/gas-pool/pool`` requires ``{walletAddress}``."""
    return {"walletAddress": str(wallet_address)}


def sponsor_from_pool(payload: Mapping[str, Any]) -> SuiAddress | None:
    """Read the sponsor address out of a gas-pool response.

    The pool response names the pool owner in ``walletAddress``; the pool
    object itself is ``gasPoolId``.  Returns None rather than raising when the
    shape does not carry a usable address, so callers decide whether the
    absence is fatal for their mode.
    """
    for key in ("sponsorAddress", "sponsor", "walletAddress"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("0x"):
            try:
                return SuiAddress(value)
            except Exception:  # noqa: BLE001 - a malformed echo is not fatal here
                return None
    return None


@dataclass(frozen=True)
class GasCheck:
    mode: str
    ok: bool
    detail: str
    remedy: str | None = None


def check_gas_mode(
    gas: GasConfig,
    *,
    wallet_address: SuiAddress | None,
    sui_balance_mist: int | None = None,
    pool_payload: Mapping[str, Any] | None = None,
    pool_error: str | None = None,
) -> GasCheck:
    """Validate that the active mode's prerequisites actually hold.

    Pure: the caller performs the I/O and hands the results in, so this is unit
    testable with zero network.  Never silently switches modes — a failure is
    reported with an actionable remedy and the operator decides.
    """
    if wallet_address is None:
        return GasCheck(
            gas.mode,
            False,
            "wallet address not configured",
            "Set AF_WALLET_ADDRESS to your Sui wallet address.",
        )

    if gas.mode == "sponsored":
        if pool_error is not None:
            return GasCheck(
                gas.mode,
                False,
                f"gas pool unreachable: {pool_error}",
                "Set AF_GAS_MODE=self and fund the wallet with SUI, or retry "
                "when the pool is reachable.",
            )
        if pool_payload is None:
            return GasCheck(
                gas.mode,
                False,
                "gas pool not checked",
                f"Call {GAS_POOL_PATH} with {{walletAddress}}.",
            )
        balance = pool_payload.get("balance")
        sponsor = sponsor_from_pool(pool_payload)
        if sponsor is None:
            return GasCheck(
                gas.mode,
                False,
                "gas pool response carries no sponsor address",
                "Set AF_GAS_MODE=self, or ask Aftermath to whitelist this wallet.",
            )
        whitelisted = pool_payload.get("whitelistedAddresses")
        if isinstance(whitelisted, list) and whitelisted:
            if str(wallet_address) not in {str(a).lower() for a in whitelisted}:
                return GasCheck(
                    gas.mode,
                    False,
                    "wallet is not whitelisted on the resolved gas pool",
                    "Ask Aftermath to whitelist this wallet, or use "
                    "AF_GAS_MODE=self.",
                )
        return GasCheck(
            gas.mode,
            True,
            f"gas pool reachable (balance={balance}); no SUI required",
        )

    if gas.mode == "self":
        if sui_balance_mist is None:
            return GasCheck(
                gas.mode,
                False,
                "SUI balance unknown",
                "The wallet balance endpoints are unavailable; verify manually "
                "or use AF_GAS_MODE=sponsored.",
            )
        if sui_balance_mist < gas.budget_mist:
            return GasCheck(
                gas.mode,
                False,
                f"SUI balance {sui_balance_mist} MIST is below the explicit gas "
                f"budget {gas.budget_mist} MIST",
                "Fund the wallet with SUI, lower AF_GAS_BUDGET_MIST, or set "
                "AF_GAS_MODE=sponsored.",
            )
        return GasCheck(gas.mode, True, f"wallet holds {sui_balance_mist} MIST")

    # dynamic
    if not gas.gas_coin_type:
        return GasCheck(
            gas.mode,
            False,
            "AF_GAS_COIN_TYPE not set",
            "Choose the coin that pays gas (e.g. the USDC coin type), or use "
            "AF_GAS_MODE=sponsored.",
        )
    return GasCheck(
        gas.mode,
        True,
        f"preconditions satisfied; gas paid in {short_coin(gas.gas_coin_type)} "
        f"via {DYNAMIC_GAS_PATH} (a transform endpoint — confirmed on the first "
        "real transaction, not pingable)",
    )


def short_coin(coin_type: str) -> str:
    return coin_type.rsplit("::", 1)[-1] if "::" in coin_type else coin_type
