"""Automatic account discovery — the turnkey path.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

The operator supplies one thing: their wallet address.  Everything else is
discovered.

Verified contract:

* ``POST /api/perpetuals/accounts/owned`` requires ``{walletAddress}`` (and
  optionally ``{collateralCoinTypes}``) and answers ``{"accountCaps": [...]}``
  — an object, NOT a bare array.
* each cap carries ``accountId`` (the NUMERIC native id), ``objectId`` (the
  CAPABILITY object id — a different identifier), ``accountObjectId``,
  ``collateralCoinType``, ``collateral``, ``isAgent`` and
  ``whitelistedAgentCapIds``.

``accountId`` and ``objectId`` are the two identifiers that get confused most
often, so they are returned as distinct types (``NativeAccountId`` and
``AccountCapId``) rather than as strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .errors import ContractError, NormalizationError
from .ids import AccountCapId, NativeAccountId, SuiAddress

OWNED_ACCOUNTS_PATH = "/api/perpetuals/accounts/owned"


@dataclass(frozen=True)
class AccountCapability:
    account_id: NativeAccountId
    cap_object_id: AccountCapId
    account_object_id: str
    collateral_coin_type: str
    collateral: float
    is_agent: bool
    wallet_address: SuiAddress | None
    raw: Mapping[str, Any]

    @classmethod
    def from_api(cls, row: Mapping[str, Any]) -> "AccountCapability":
        if not isinstance(row, Mapping):
            raise ContractError("accountCaps row must be an object")
        raw_collateral = row.get("collateral", 0)
        if isinstance(raw_collateral, str) and raw_collateral.endswith("n"):
            collateral = float(raw_collateral[:-1])
        elif isinstance(raw_collateral, (int, float)) and not isinstance(
            raw_collateral, bool
        ):
            collateral = float(raw_collateral)
        else:
            raise NormalizationError(
                f"accountCaps.collateral is not numeric: {raw_collateral!r}"
            )
        wallet_raw = row.get("walletAddress")
        return cls(
            account_id=NativeAccountId(row.get("accountId")),
            cap_object_id=AccountCapId(row.get("objectId")),
            account_object_id=str(row.get("accountObjectId", "")),
            collateral_coin_type=str(row.get("collateralCoinType", "")),
            collateral=collateral,
            is_agent=bool(row.get("isAgent", False)),
            wallet_address=(
                SuiAddress(wallet_raw) if isinstance(wallet_raw, str) and wallet_raw else None
            ),
            raw=row,
        )


def owned_accounts_request(
    wallet_address: SuiAddress,
    collateral_coin_types: Sequence[str] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"walletAddress": str(wallet_address)}
    if collateral_coin_types:
        body["collateralCoinTypes"] = list(collateral_coin_types)
    return body


def parse_owned_accounts(payload: Any) -> tuple[AccountCapability, ...]:
    if not isinstance(payload, Mapping):
        raise ContractError(
            f"{OWNED_ACCOUNTS_PATH} must answer an object with 'accountCaps'; a "
            "bare array means the wrong endpoint or API version"
        )
    rows = payload.get("accountCaps")
    if rows is None:
        raise ContractError(f"{OWNED_ACCOUNTS_PATH} response has no 'accountCaps' key")
    if not isinstance(rows, list):
        raise ContractError(f"{OWNED_ACCOUNTS_PATH} 'accountCaps' must be an array")
    return tuple(AccountCapability.from_api(row) for row in rows)


def select_account(
    caps: Sequence[AccountCapability],
    *,
    collateral_coin_type: str,
    preferred_account_id: int | None = None,
) -> AccountCapability | None:
    """Choose the account this runtime will act through.

    Deterministic and explicit: an operator-pinned id wins; otherwise the
    matching-collateral account with the largest collateral, tie-broken by the
    lowest account id.  Returns None when the wallet owns no matching account,
    which is a guidable state, not an error.
    """
    if preferred_account_id is not None:
        wanted = NativeAccountId(preferred_account_id)
        for cap in caps:
            if cap.account_id == wanted:
                return cap
        raise ContractError(
            f"AF_ACCOUNT_ID={preferred_account_id} is not owned by this wallet; "
            f"owned: {[c.account_id.value for c in caps]}"
        )
    matching = [
        cap
        for cap in caps
        if not cap.is_agent and cap.collateral_coin_type == collateral_coin_type
    ]
    if not matching:
        return None
    return sorted(matching, key=lambda c: (-c.collateral, c.account_id.value))[0]
