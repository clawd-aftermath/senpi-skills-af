"""Atomic execution primitives against the Aftermath V2 native surface.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

One-operation-per-transaction is the shallow-port failure mode.  Every route
used here was verified present in the live V2 OpenAPI document, and multi-step
intents are expressed as ONE transaction wherever the API offers a primitive
for it:

* **every requote/reprice/modify goes through ``cancel-and-place-orders``.**  A
  split cancel-then-place leaves the strategy unquoted or double-quoted in
  between, and can partially fail.
* **a ladder is ``place-scale-order``** — one transaction, not N places.
* **onboarding is one composed PTB** — ``create-account`` with ``txKind`` and
  ``deferShare`` returns a transaction *kind* and deferred PTB argument
  references, which the deposit and allocate builders then extend via their own
  ``txKind`` parameter.  Either the whole onboarding lands or none of it does,
  instead of stranding an operator half-set-up.

Nothing here signs or submits.  Every method returns an ``InspectedTx``: built,
preview-gated where a preview counterpart exists, and inspected.

Wire format: the native BigInt fields listed in ``BIGINT_REQUEST_FIELDS`` are
serialised as exact ``"...n"`` strings, per each field's own OpenAPI
description ("encoded from a BigInt-style string such as ``\"123n\"``") and the
pinned skills rule.  Fields the spec types as plain numbers stay plain numbers;
this is deliberately not a blanket conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .errors import ConfigError, NormalizationError, WriteDenied
from .gas import GasConfig
from .ids import (
    AccountCapId,
    MarketId,
    NativeAccountId,
    SuiAddress,
    side_to_native,
    to_bigint_wire,
)
from .ptb import InspectedTx, PtbPipeline, TxIntent

ACCOUNT_TX = "/api/perpetuals/account/transactions"
ACCOUNT_PREVIEW = "/api/perpetuals/account/previews"

CANCEL_AND_PLACE_PATH = f"{ACCOUNT_TX}/cancel-and-place-orders"
SCALE_ORDER_PATH = f"{ACCOUNT_TX}/place-scale-order"
MARKET_ORDER_PATH = f"{ACCOUNT_TX}/place-market-order"
LIMIT_ORDER_PATH = f"{ACCOUNT_TX}/place-limit-order"
CANCEL_ORDERS_PATH = f"{ACCOUNT_TX}/cancel-orders"
SET_LEVERAGE_PATH = f"{ACCOUNT_TX}/set-leverage"
DEPOSIT_PATH = f"{ACCOUNT_TX}/deposit-collateral"
ALLOCATE_PATH = f"{ACCOUNT_TX}/allocate-collateral"
DEALLOCATE_PATH = f"{ACCOUNT_TX}/deallocate-collateral"
WITHDRAW_PATH = f"{ACCOUNT_TX}/withdraw-collateral"
TRANSFER_PATH = f"{ACCOUNT_TX}/transfer-collateral"
SL_TP_PATH = f"{ACCOUNT_TX}/place-sl-tp-orders"
STOP_ORDERS_PATH = f"{ACCOUNT_TX}/place-stop-orders"
EDIT_STOP_ORDERS_PATH = f"{ACCOUNT_TX}/edit-stop-orders"
CANCEL_STOP_ORDERS_PATH = f"{ACCOUNT_TX}/cancel-stop-orders"
CREATE_TWAP_PATH = f"{ACCOUNT_TX}/create-twap-orders"
EDIT_TWAP_PATH = f"{ACCOUNT_TX}/edit-twap-orders"
CANCEL_TWAP_PATH = f"{ACCOUNT_TX}/cancel-twap-orders"
CREATE_ACCOUNT_PATH = "/api/perpetuals/transactions/create-account"
MAX_ORDER_SIZE_PATH = "/api/perpetuals/account/max-order-size"

PREVIEW_MARKET_ORDER_PATH = f"{ACCOUNT_PREVIEW}/place-market-order"
PREVIEW_LIMIT_ORDER_PATH = f"{ACCOUNT_PREVIEW}/place-limit-order"
PREVIEW_SCALE_ORDER_PATH = f"{ACCOUNT_PREVIEW}/place-scale-order"
PREVIEW_CANCEL_ORDERS_PATH = f"{ACCOUNT_PREVIEW}/cancel-orders"
PREVIEW_SET_LEVERAGE_PATH = f"{ACCOUNT_PREVIEW}/set-leverage"
PREVIEW_EDIT_COLLATERAL_PATH = f"{ACCOUNT_PREVIEW}/edit-collateral"

# Exactly the request fields whose own OpenAPI description specifies the
# BigInt-style trailing-"n" encoding.  Derived from the live spec, not memory.
BIGINT_REQUEST_FIELDS = frozenset(
    {
        "accountId",
        "accountIds",
        "allocateAmount",
        "clientOrderId",
        "clientOrderIds",
        "clientOrderIdsToCancel",
        "deallocateAmount",
        "depositAmount",
        "endPrice",
        "expiryTimestamp",
        "fromAccountId",
        "limitOrderId",
        "orderIds",
        "orderIdsToCancel",
        "price",
        "size",
        "startPrice",
        "toAccountId",
        "totalSize",
        "transferAmount",
        "withdrawAmount",
    }
)

# Order type enum on the native surface (ApiPerpetualsLimitOrderBody.orderType).
ORDER_TYPE_STANDARD = 0
ORDER_TYPE_POST_ONLY = 1
ORDER_TYPE_FILL_OR_KILL = 2
ORDER_TYPE_IMMEDIATE_OR_CANCEL = 3

# triggerPriceType: 0 index, 1 book mid, 2 mark.
TRIGGER_INDEX = 0
TRIGGER_BOOK_MID = 1
TRIGGER_MARK = 2


def encode_bigints(body: Mapping[str, Any]) -> dict[str, Any]:
    """Encode the documented native BigInt fields as exact ``"...n"`` strings."""
    out: dict[str, Any] = {}
    for key, value in body.items():
        if value is None or key not in BIGINT_REQUEST_FIELDS:
            out[key] = value
            continue
        if isinstance(value, (list, tuple)):
            out[key] = [to_bigint_wire(int(item), key) for item in value]
        elif isinstance(value, bool):
            raise NormalizationError(f"{key} must be an integer, not a bool")
        elif isinstance(value, int):
            out[key] = to_bigint_wire(value, key)
        elif isinstance(value, str) and value.endswith("n"):
            out[key] = value
        else:
            raise NormalizationError(
                f"{key} is a native BigInt field and must be an integer, got "
                f"{value!r}"
            )
    return out


@dataclass(frozen=True)
class OrderToPlace:
    """One rung of a quote.  ``side`` is the native numeric enum: 0 bid, 1 ask."""

    side: int | str
    price_native: int
    size_native: int
    client_order_id: int | None = None

    def as_body(self) -> dict[str, Any]:
        if self.price_native <= 0 or self.size_native <= 0:
            raise NormalizationError("order price and size must be positive")
        body: dict[str, Any] = {
            "side": side_to_native(self.side),
            "price": self.price_native,
            "size": self.size_native,
        }
        if self.client_order_id is not None:
            body["clientOrderId"] = self.client_order_id
        return encode_bigints(body)


@dataclass(frozen=True)
class AccountRef:
    """Identifies the acting account.

    Native routes take the numeric ``accountId`` (BigInt wire) and optionally
    the capability object id.  The two are DIFFERENT identifiers and are typed
    separately so they cannot be swapped.
    """

    account_id: NativeAccountId
    wallet_address: SuiAddress
    account_cap_id: AccountCapId | None = None

    def as_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "accountId": self.account_id.as_number(),
            "walletAddress": str(self.wallet_address),
        }
        if self.account_cap_id is not None:
            body["accountCapId"] = str(self.account_cap_id)
        return body


class ExecutionClient:
    """Builds Aftermath V2 transactions.  Never signs, never submits.

    ``armed`` gates every builder.  With ``armed=False`` (the default, and what
    this repository ships) each method raises ``WriteDenied`` before any
    request is made, so a strategy left enabled by accident cannot even
    construct a transaction.
    """

    def __init__(
        self,
        transport: Any,
        *,
        gas: GasConfig,
        armed: bool = False,
    ) -> None:
        self._pipeline = PtbPipeline(transport)
        self._gas = gas
        self._armed = bool(armed)

    @property
    def armed(self) -> bool:
        return self._armed

    def _guard(self, intent: str) -> None:
        if not self._armed:
            raise WriteDenied(
                f"refusing to build {intent}: the runtime is not armed. "
                "Arming is a single explicit flag (AF_ARMED=1) and every "
                "strategy in this repository ships disabled."
            )

    def _intent(
        self,
        label: str,
        build_path: str,
        sender: SuiAddress,
        *,
        expects_deferred: bool = False,
    ) -> TxIntent:
        return TxIntent(
            intent=label,
            sender=sender,
            gas=self._gas,
            build_path=build_path,
            expects_deferred=expects_deferred,
        )

    # ── The requote primitive ────────────────────────────────────

    def cancel_and_place(
        self,
        account: AccountRef,
        market: MarketId,
        *,
        orders_to_place: Sequence[OrderToPlace] = (),
        order_ids_to_cancel: Sequence[int] = (),
        client_order_ids_to_cancel: Sequence[int] = (),
        order_type: int = ORDER_TYPE_STANDARD,
        reduce_only: bool = False,
        has_position: bool = False,
        leverage: float | None = None,
        expiry_timestamp: int | None = None,
        should_abort_on_missing_id: bool = True,
        should_deallocate_free_collateral: bool = False,
    ) -> InspectedTx:
        """ONE transaction that cancels and re-places.

        Use this for EVERY requote.  ``shouldAbortOnMissingId`` defaults to
        True: if an order we meant to cancel has already gone, the whole
        transaction aborts rather than silently placing a new quote on top of a
        fill we have not observed yet.
        """
        self._guard("cancel-and-place-orders")
        if not orders_to_place and not order_ids_to_cancel and not client_order_ids_to_cancel:
            raise NormalizationError(
                "cancel-and-place needs at least one order to cancel or place"
            )
        body: dict[str, Any] = {
            **account.as_body(),
            "marketId": str(market),
            "orderType": int(order_type),
            "reduceOnly": bool(reduce_only),
            "hasPosition": bool(has_position),
            "shouldAbortOnMissingId": bool(should_abort_on_missing_id),
            "shouldDeallocateFreeCollateral": bool(should_deallocate_free_collateral),
        }
        if orders_to_place:
            body["ordersToPlace"] = [order.as_body() for order in orders_to_place]
        if order_ids_to_cancel:
            body["orderIdsToCancel"] = list(order_ids_to_cancel)
        if client_order_ids_to_cancel:
            body["clientOrderIdsToCancel"] = list(client_order_ids_to_cancel)
        if leverage is not None:
            body["leverage"] = float(leverage)
        if expiry_timestamp is not None:
            body["expiryTimestamp"] = int(expiry_timestamp)
        return self._pipeline.build(
            self._intent("cancel-and-place-orders", CANCEL_AND_PLACE_PATH, account.wallet_address),
            encode_bigints(body),
        )

    # ── The ladder primitive ─────────────────────────────────────

    def place_scale_order(
        self,
        account: AccountRef,
        market: MarketId,
        *,
        side: int | str,
        start_price_native: int,
        end_price_native: int,
        number_of_orders: int,
        total_size_native: int,
        collateral_change: float,
        size_skew: float | None = None,
        order_type: int = ORDER_TYPE_POST_ONLY,
        reduce_only: bool = False,
        has_position: bool = False,
        cancel_sl_tp: bool = False,
        leverage: float | None = None,
        client_order_ids: Sequence[int] = (),
        expiry_timestamp: int | None = None,
    ) -> InspectedTx:
        """A whole ladder in ONE transaction, preview-gated."""
        self._guard("place-scale-order")
        if number_of_orders < 1:
            raise NormalizationError("a scale order needs at least one rung")
        body: dict[str, Any] = {
            **account.as_body(),
            "marketId": str(market),
            "side": side_to_native(side),
            "orderType": int(order_type),
            "startPrice": int(start_price_native),
            "endPrice": int(end_price_native),
            "numberOfOrders": int(number_of_orders),
            "totalSize": int(total_size_native),
            "collateralChange": float(collateral_change),
            "reduceOnly": bool(reduce_only),
            "hasPosition": bool(has_position),
            "cancelSlTp": bool(cancel_sl_tp),
        }
        if size_skew is not None:
            body["sizeSkew"] = float(size_skew)
        if leverage is not None:
            body["leverage"] = float(leverage)
        if client_order_ids:
            body["clientOrderIds"] = list(client_order_ids)
        if expiry_timestamp is not None:
            body["expiryTimestamp"] = int(expiry_timestamp)
        preview_body = encode_bigints(
            {
                "accountId": account.account_id.as_number(),
                "marketId": str(market),
                "side": side_to_native(side),
                "orderType": int(order_type),
                "startPrice": int(start_price_native),
                "endPrice": int(end_price_native),
                "numberOfOrders": int(number_of_orders),
                "totalSize": int(total_size_native),
                "reduceOnly": bool(reduce_only),
            }
        )
        return self._pipeline.build(
            self._intent("place-scale-order", SCALE_ORDER_PATH, account.wallet_address),
            encode_bigints(body),
            preview_path=PREVIEW_SCALE_ORDER_PATH,
            preview_body=preview_body,
        )

    # ── Single orders ────────────────────────────────────────────

    def place_market_order(
        self,
        account: AccountRef,
        market: MarketId,
        *,
        side: int | str,
        size_native: int,
        collateral_change: float,
        slippage: float,
        reduce_only: bool = False,
        has_position: bool = False,
        cancel_sl_tp: bool = False,
        leverage: float | None = None,
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
        trigger_price_type: int = TRIGGER_MARK,
    ) -> InspectedTx:
        """A market order, preview-gated, with optional attached SL/TP.

        v3.0.0 renamed ``stopLossIndexPrice``/``takeProfitIndexPrice`` to
        ``stopLossPrice``/``takeProfitPrice``; only the new names are emitted.
        """
        self._guard("place-market-order")
        body: dict[str, Any] = {
            **account.as_body(),
            "marketId": str(market),
            "side": side_to_native(side),
            "size": int(size_native),
            "collateralChange": float(collateral_change),
            "slippage": float(slippage),
            "reduceOnly": bool(reduce_only),
            "hasPosition": bool(has_position),
            "cancelSlTp": bool(cancel_sl_tp),
        }
        if leverage is not None:
            body["leverage"] = float(leverage)
        if stop_loss_price is not None or take_profit_price is not None:
            sl_tp: dict[str, Any] = {"triggerPriceType": int(trigger_price_type)}
            if stop_loss_price is not None:
                sl_tp["stopLossPrice"] = float(stop_loss_price)
            if take_profit_price is not None:
                sl_tp["takeProfitPrice"] = float(take_profit_price)
            body["slTp"] = sl_tp
        preview_body = encode_bigints(
            {
                "accountId": account.account_id.as_number(),
                "marketId": str(market),
                "side": side_to_native(side),
                "size": int(size_native),
                "reduceOnly": bool(reduce_only),
                **({"leverage": float(leverage)} if leverage is not None else {}),
            }
        )
        return self._pipeline.build(
            self._intent("place-market-order", MARKET_ORDER_PATH, account.wallet_address),
            encode_bigints(body),
            preview_path=PREVIEW_MARKET_ORDER_PATH,
            preview_body=preview_body,
        )

    def place_limit_order(
        self,
        account: AccountRef,
        market: MarketId,
        *,
        side: int | str,
        price_native: int,
        size_native: int,
        collateral_change: float,
        order_type: int = ORDER_TYPE_POST_ONLY,
        reduce_only: bool = False,
        has_position: bool = False,
        cancel_sl_tp: bool = False,
        leverage: float | None = None,
        client_order_id: int | None = None,
        expiry_timestamp: int | None = None,
    ) -> InspectedTx:
        self._guard("place-limit-order")
        body: dict[str, Any] = {
            **account.as_body(),
            "marketId": str(market),
            "side": side_to_native(side),
            "price": int(price_native),
            "size": int(size_native),
            "orderType": int(order_type),
            "collateralChange": float(collateral_change),
            "reduceOnly": bool(reduce_only),
            "hasPosition": bool(has_position),
            "cancelSlTp": bool(cancel_sl_tp),
        }
        if leverage is not None:
            body["leverage"] = float(leverage)
        if client_order_id is not None:
            body["clientOrderId"] = int(client_order_id)
        if expiry_timestamp is not None:
            body["expiryTimestamp"] = int(expiry_timestamp)
        preview_body = encode_bigints(
            {
                "accountId": account.account_id.as_number(),
                "marketId": str(market),
                "side": side_to_native(side),
                "price": int(price_native),
                "size": int(size_native),
                "orderType": int(order_type),
                "reduceOnly": bool(reduce_only),
            }
        )
        return self._pipeline.build(
            self._intent("place-limit-order", LIMIT_ORDER_PATH, account.wallet_address),
            encode_bigints(body),
            preview_path=PREVIEW_LIMIT_ORDER_PATH,
            preview_body=preview_body,
        )

    def cancel_orders(
        self,
        account: AccountRef,
        market_ids_to_data: Mapping[str, Any],
        *,
        should_abort_on_missing_id: bool = False,
        should_deallocate_free_collateral: bool = False,
    ) -> InspectedTx:
        """Cancel across one or more markets in ONE transaction.

        ``shouldAbortOnMissingId`` defaults to False here — the opposite of the
        requote path — because a cancel-all must succeed even when some orders
        have already filled or expired.
        """
        self._guard("cancel-orders")
        body: dict[str, Any] = {
            **account.as_body(),
            "marketIdsToData": dict(market_ids_to_data),
            "shouldAbortOnMissingId": bool(should_abort_on_missing_id),
        }
        preview_body = {
            "accountId": account.account_id.as_number(),
            "marketIdsToData": dict(market_ids_to_data),
            "shouldAbortOnMissingId": bool(should_abort_on_missing_id),
            "shouldDeallocateFreeCollateral": bool(should_deallocate_free_collateral),
        }
        return self._pipeline.build(
            self._intent("cancel-orders", CANCEL_ORDERS_PATH, account.wallet_address),
            encode_bigints(body),
            preview_path=PREVIEW_CANCEL_ORDERS_PATH,
            preview_body=encode_bigints(preview_body),
        )

    def set_leverage(
        self,
        account: AccountRef,
        market: MarketId,
        *,
        leverage: float,
        collateral_change: float = 0.0,
    ) -> InspectedTx:
        self._guard("set-leverage")
        if leverage <= 0:
            raise NormalizationError("leverage must be positive")
        body = {
            **account.as_body(),
            "marketId": str(market),
            "leverage": float(leverage),
            "collateralChange": float(collateral_change),
        }
        return self._pipeline.build(
            self._intent("set-leverage", SET_LEVERAGE_PATH, account.wallet_address),
            encode_bigints(body),
            preview_path=PREVIEW_SET_LEVERAGE_PATH,
            preview_body=encode_bigints(
                {
                    "accountId": account.account_id.as_number(),
                    "marketId": str(market),
                    "leverage": float(leverage),
                }
            ),
        )

    # ── Isolated-collateral lifecycle ────────────────────────────

    def deposit_collateral(
        self,
        account: AccountRef,
        *,
        collateral_coin_type: str,
        deposit_amount: int,
        tx_kind: str | None = None,
    ) -> InspectedTx:
        """Wallet -> account UNALLOCATED collateral.

        Unallocated collateral protects no position.  ``allocate_collateral``
        is the step that actually gives a position margin.
        """
        self._guard("deposit-collateral")
        if deposit_amount <= 0:
            raise NormalizationError("deposit amount must be positive")
        body: dict[str, Any] = {
            **account.as_body(),
            "collateralCoinType": collateral_coin_type,
            "depositAmount": int(deposit_amount),
        }
        if tx_kind is not None:
            body["txKind"] = tx_kind
        return self._pipeline.build(
            self._intent("deposit-collateral", DEPOSIT_PATH, account.wallet_address),
            encode_bigints(body),
        )

    def allocate_collateral(
        self,
        account: AccountRef,
        market: MarketId,
        *,
        allocate_amount: int,
        tx_kind: str | None = None,
    ) -> InspectedTx:
        """Account unallocated collateral -> this position's ISOLATED margin."""
        self._guard("allocate-collateral")
        if allocate_amount <= 0:
            raise NormalizationError("allocate amount must be positive")
        body: dict[str, Any] = {
            **account.as_body(),
            "marketId": str(market),
            "allocateAmount": int(allocate_amount),
        }
        if tx_kind is not None:
            body["txKind"] = tx_kind
        return self._pipeline.build(
            self._intent("allocate-collateral", ALLOCATE_PATH, account.wallet_address),
            encode_bigints(body),
        )

    def deallocate_collateral(
        self, account: AccountRef, market: MarketId, *, deallocate_amount: int
    ) -> InspectedTx:
        self._guard("deallocate-collateral")
        body = {
            **account.as_body(),
            "marketId": str(market),
            "deallocateAmount": int(deallocate_amount),
        }
        return self._pipeline.build(
            self._intent("deallocate-collateral", DEALLOCATE_PATH, account.wallet_address),
            encode_bigints(body),
            preview_path=PREVIEW_EDIT_COLLATERAL_PATH,
            preview_body=encode_bigints(
                {
                    "accountId": account.account_id.as_number(),
                    "marketId": str(market),
                    "collateralChange": -int(deallocate_amount),
                }
            ),
        )

    def withdraw_collateral(
        self,
        account: AccountRef,
        *,
        withdraw_amount: int,
        recipient_address: SuiAddress | None = None,
    ) -> InspectedTx:
        self._guard("withdraw-collateral")
        body: dict[str, Any] = {
            "accountId": account.account_id.as_number(),
            "withdrawAmount": int(withdraw_amount),
        }
        if recipient_address is not None:
            body["recipientAddress"] = str(recipient_address)
        return self._pipeline.build(
            self._intent("withdraw-collateral", WITHDRAW_PATH, account.wallet_address),
            encode_bigints(body),
        )

    # ── Stops / SL-TP ────────────────────────────────────────────

    def place_sl_tp_orders(
        self,
        account: AccountRef,
        market: MarketId,
        *,
        position_side: int | str,
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
        size_native: int | None = None,
        limit_order_id: int | None = None,
        trigger_price_type: int = TRIGGER_MARK,
    ) -> InspectedTx:
        """Stop-loss and take-profit in ONE transaction.

        v3.0.0 field names only: ``stopLossPrice`` / ``takeProfitPrice``.
        """
        self._guard("place-sl-tp-orders")
        if stop_loss_price is None and take_profit_price is None:
            raise NormalizationError("SL/TP needs at least one of stop or target")
        body: dict[str, Any] = {
            **account.as_body(),
            "marketId": str(market),
            "positionSide": side_to_native(position_side),
            "triggerPriceType": int(trigger_price_type),
        }
        if stop_loss_price is not None:
            body["stopLossPrice"] = float(stop_loss_price)
        if take_profit_price is not None:
            body["takeProfitPrice"] = float(take_profit_price)
        if size_native is not None:
            body["size"] = int(size_native)
        if limit_order_id is not None:
            body["limitOrderId"] = int(limit_order_id)
        return self._pipeline.build(
            self._intent("place-sl-tp-orders", SL_TP_PATH, account.wallet_address),
            encode_bigints(body),
        )

    def place_stop_orders(
        self, account: AccountRef, stop_orders: Sequence[Mapping[str, Any]]
    ) -> InspectedTx:
        self._guard("place-stop-orders")
        if not stop_orders:
            raise NormalizationError("place-stop-orders needs at least one order")
        body = {**account.as_body(), "stopOrders": [dict(o) for o in stop_orders]}
        return self._pipeline.build(
            self._intent("place-stop-orders", STOP_ORDERS_PATH, account.wallet_address),
            encode_bigints(body),
        )

    # ── Composed onboarding ──────────────────────────────────────

    def build_onboarding_ptb(
        self,
        wallet_address: SuiAddress,
        *,
        collateral_coin_type: str,
        deposit_amount: int,
        allocations: Sequence[tuple[MarketId, int]] = (),
    ) -> InspectedTx:
        """create-account + deposit + allocate as ONE atomic PTB.

        The chain is built by threading ``txKind`` through: ``create-account``
        returns a transaction *kind*, which the deposit builder extends, which
        the allocate builder extends again.  The result succeeds or fails as a
        unit, instead of stranding an operator with an account and no
        collateral, or collateral allocated to nothing.

        ``deferShare=true`` is used so the account object stays available as a
        PTB argument for the deposit step.  Its response carries **deferred PTB
        argument references** in addition to ``txKind`` — the inspection gate
        asserts they are present rather than assuming the simple ``{txKind}``
        shape (``gotchas.md`` §12).

        NOTE — honest limitation: threading the deferred ``accountArg`` into the
        deposit step requires composing the PTB with a Sui SDK.  Because the
        deposit builder identifies the account by ``accountId`` (which does not
        exist until the create-account command executes), a fully composed
        three-step PTB additionally needs the deferred argument references to be
        substituted client-side.  This method builds and inspects the
        create-account kind and returns it with those references attached; the
        caller supplies the Sui PTB composition.  ``deposit_amount`` and
        ``allocations`` are recorded on the intent so the composition step
        cannot drift from what was previewed.
        """
        self._guard("composed onboarding PTB")
        if deposit_amount <= 0:
            raise NormalizationError("onboarding deposit must be positive")
        for _market, amount in allocations:
            if amount <= 0:
                raise NormalizationError("onboarding allocation must be positive")
        body: dict[str, Any] = {
            "walletAddress": str(wallet_address),
            "collateralCoinType": collateral_coin_type,
            "deferShare": True,
        }
        return self._pipeline.build(
            self._intent(
                "create-account (composed onboarding)",
                CREATE_ACCOUNT_PATH,
                wallet_address,
                expects_deferred=True,
            ),
            body,
        )

    def create_account(
        self,
        wallet_address: SuiAddress,
        *,
        collateral_coin_type: str,
        defer_share: bool = False,
        tx_kind: str | None = None,
    ) -> InspectedTx:
        self._guard("create-account")
        body: dict[str, Any] = {
            "walletAddress": str(wallet_address),
            "collateralCoinType": collateral_coin_type,
            "deferShare": bool(defer_share),
        }
        if tx_kind is not None:
            body["txKind"] = tx_kind
        return self._pipeline.build(
            self._intent(
                "create-account",
                CREATE_ACCOUNT_PATH,
                wallet_address,
                expects_deferred=defer_share,
            ),
            body,
        )


def max_order_size_request(
    account_id: NativeAccountId,
    market: MarketId,
    *,
    side: int | str,
    price: float | None = None,
    leverage: float | None = None,
) -> dict[str, Any]:
    """Body for ``/api/perpetuals/account/max-order-size``.

    Guard large orders with this before building them, per the safety skill.
    """
    body: dict[str, Any] = {
        "accountId": account_id.as_number(),
        "marketId": str(market),
        "side": side_to_native(side),
    }
    if price is not None:
        body["price"] = float(price)
    if leverage is not None:
        body["leverage"] = float(leverage)
    # `price` on this route is a plain double, not a BigInt field — encode only
    # the accountId.
    body["accountId"] = to_bigint_wire(account_id.as_number(), "accountId")
    return body


def assert_no_venue_leakage(body: Mapping[str, Any]) -> None:
    """Fail closed if Hyperliquid semantics survived into a request body.

    ``marginPct``, ``leverage``-as-sizing, HIP-3 ``xyz:`` prefixes and dex-local
    asset-id arithmetic have no meaning on Aftermath.  Any of them reaching a
    request body means an upstream concept was re-pointed instead of replaced.
    """
    forbidden = {"marginPct", "margin_pct", "coin", "szi", "dex", "destinationDex", "sendAsset"}
    present = forbidden & set(body)
    if present:
        raise ConfigError(
            f"upstream venue fields leaked into an Aftermath request: "
            f"{sorted(present)}. Aftermath sizes by explicit collateral "
            "allocation against an API-resolved marketId."
        )
    for key, value in body.items():
        if isinstance(value, str) and value.lower().startswith("xyz:"):
            raise ConfigError(
                f"{key} carries a HIP-3 dex prefix ({value!r}); Aftermath "
                "marketIds are API-issued object ids and are never constructed"
            )
