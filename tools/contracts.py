#!/usr/bin/env python3
"""Small fail-closed validators for overlay request models.

These validate the typed overlay boundary, not arbitrary HTTP payloads.
Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any


class ContractError(ValueError):
    """Raised when a request crosses the overlay boundary with an unsafe shape."""


def validate_positions_request(payload: dict[str, Any]) -> None:
    if "accountId" in payload:
        raise ContractError("positions requires accountIds[], not accountId")
    account_ids = payload.get("accountIds")
    if not isinstance(account_ids, list) or not account_ids:
        raise ContractError("positions requires a non-empty accountIds array")
    if not all(isinstance(value, int) and value >= 0 for value in account_ids):
        raise ContractError("accountIds must contain non-negative integers")
    allowed = {"accountIds", "marketIds"}
    extras = set(payload) - allowed
    if extras:
        raise ContractError(f"unexpected positions fields: {sorted(extras)}")


def validate_cancel_and_place_body(payload: dict[str, Any]) -> None:
    """Validate route-neutral order fields.

    Account identity is a separate typed argument to the HTTP adapter. Keeping it
    out of this generic body avoids the legacy request's ambiguous duplicated
    `accountId` / `accountCapId` fields.
    """

    forbidden = {"accountId", "accountCapId"}
    extras = forbidden.intersection(payload)
    if extras:
        raise ContractError(
            f"account identity is not an order-body field: {sorted(extras)}"
        )
    required = {"walletAddress", "marketId", "orderType", "reduceOnly", "hasPosition"}
    missing = required - set(payload)
    if missing:
        raise ContractError(f"missing cancel-and-place fields: {sorted(missing)}")
    allowed = required | {
        "builderCode",
        "clientOrderIdsToCancel",
        "expiryTimestamp",
        "leverage",
        "orderIdsToCancel",
        "ordersToPlace",
        "shouldAbortOnMissingId",
        "shouldDeallocateFreeCollateral",
        "sponsor",
        "txKind",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ContractError(f"unexpected cancel-and-place fields: {sorted(unknown)}")
