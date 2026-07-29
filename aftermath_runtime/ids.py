"""Distinct identifier types for the Aftermath V2 API.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

Three different things are all loosely called "the account", and mixing them up
is the single most common integration failure against this API (skills v3.0.0,
``gotchas.md`` §1):

===========================  ==============  =============================
what                         wire form       used by
===========================  ==============  =============================
native ``accountId``         ``"123n"``      native ``/api/perpetuals/*``
CCXT write ``accountId``     ``"0x..."``     ``/api/ccxt/build|submit/*``
CCXT read ``accountNumber``  ``123``         ``/api/ccxt/myPendingOrders``
===========================  ==============  =============================

A bare ``str`` or ``int`` parameter accepts all three silently and then either
fails at the API or — far worse — addresses the wrong account.  Each is a
distinct class here, constructed through a validating factory, so passing one
where another belongs raises at the boundary instead of on the wire.

BigInt wire format (``gotchas.md`` §11): native BigInt fields use the exact
``"...n"`` string on request *and* response.  Plain numbers are rejected by the
API.  Other timestamps and counters stay ordinary JSON numbers — follow the
per-endpoint type, never blanket-convert.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import NormalizationError

OBJECT_ID_RE = re.compile(r"^0x[0-9a-fA-F]{1,64}$")
_BIGINT_WIRE_RE = re.compile(r"^(\d+)n$")
_MAYBE_BIGINT_WIRE_RE = re.compile(r"^(\d+)n?$")


class _Id:
    """Base for the identifier newtypes; equality is by (class, value)."""

    __slots__ = ("value",)

    def __init__(self, value: object) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def __eq__(self, other: object) -> bool:
        return type(other) is type(self) and other.value == self.value  # type: ignore[attr-defined]

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.value))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.value!r})"

    def __str__(self) -> str:
        return str(self.value)


class NativeAccountId(_Id):
    """Numeric native perpetuals account id.  Wire form is ``"123n"``."""

    __slots__ = ()

    def __init__(self, value: "int | str | NativeAccountId") -> None:
        if isinstance(value, NativeAccountId):
            object.__setattr__(self, "value", value.value)
            return
        if isinstance(value, bool):
            raise NormalizationError("native accountId must be an integer, not a bool")
        if isinstance(value, int):
            parsed = value
        elif isinstance(value, str):
            match = _MAYBE_BIGINT_WIRE_RE.match(value.strip())
            if match is None:
                if OBJECT_ID_RE.match(value.strip()):
                    raise NormalizationError(
                        "native accountId must be numeric; an object id "
                        "('0x...') is a CCXT-write AccountCapId, not a native id"
                    )
                raise NormalizationError(
                    f"native accountId must be digits (optionally 'n'-suffixed), "
                    f"got {value!r}"
                )
            parsed = int(match.group(1))
        else:
            raise NormalizationError(
                f"native accountId must be int or str, got {type(value).__name__}"
            )
        if parsed < 0:
            raise NormalizationError("native accountId must be non-negative")
        object.__setattr__(self, "value", parsed)

    @property
    def wire(self) -> str:
        """The exact native BigInt request encoding."""
        return f"{self.value}n"

    def as_number(self) -> int:
        """The plain-integer encoding used where the schema says ``int64``."""
        return int(self.value)


class AccountCapId(_Id):
    """CCXT *write* account id: an account-capability OBJECT id (``0x...``)."""

    __slots__ = ()

    def __init__(self, value: "str | AccountCapId") -> None:
        if isinstance(value, AccountCapId):
            object.__setattr__(self, "value", value.value)
            return
        if not isinstance(value, str) or OBJECT_ID_RE.match(value.strip()) is None:
            raise NormalizationError(
                f"CCXT write accountId must be an object id ('0x...'), got {value!r}. "
                "If you meant the numeric native account id, use NativeAccountId."
            )
        object.__setattr__(self, "value", value.strip())


class AccountNumber(_Id):
    """CCXT read/stream account number: a plain JSON number."""

    __slots__ = ()

    def __init__(self, value: "int | AccountNumber") -> None:
        if isinstance(value, AccountNumber):
            object.__setattr__(self, "value", value.value)
            return
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise NormalizationError(
                f"accountNumber must be a non-negative plain integer, got {value!r}"
            )
        object.__setattr__(self, "value", value)


class MarketId(_Id):
    """A market identifier.

    NOT a ticker.  Aftermath validates these strictly; they are Sui object ids
    obtained from ``/api/perpetuals/all-markets``.  Never construct one from a
    symbol — resolve it.
    """

    __slots__ = ()

    def __init__(self, value: "str | MarketId") -> None:
        if isinstance(value, MarketId):
            object.__setattr__(self, "value", value.value)
            return
        if not isinstance(value, str) or not value.strip():
            raise NormalizationError("marketId must be a non-empty string")
        text = value.strip()
        if text.upper() == text and OBJECT_ID_RE.match(text) is None and len(text) <= 12:
            raise NormalizationError(
                f"{text!r} looks like a ticker, not a marketId. Resolve it through "
                "the market registry — Aftermath validates marketIds strictly."
            )
        object.__setattr__(self, "value", text)


class SuiAddress(_Id):
    """A Sui address (``0x`` + hex)."""

    __slots__ = ()

    def __init__(self, value: "str | SuiAddress") -> None:
        if isinstance(value, SuiAddress):
            object.__setattr__(self, "value", value.value)
            return
        if not isinstance(value, str) or OBJECT_ID_RE.match(value.strip()) is None:
            raise NormalizationError(f"invalid Sui address: {value!r}")
        object.__setattr__(self, "value", value.strip().lower())


# ── Native BigInt wire helpers ───────────────────────────────────


def to_bigint_wire(value: int, field_name: str = "value") -> str:
    """Encode a non-negative integer for a native BigInt request field."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NormalizationError(f"{field_name} must be a non-negative integer")
    return f"{value}n"


def from_bigint_wire(value: object, field_name: str = "value") -> int:
    """Decode an exact native BigInt response field (``"123n"`` -> ``123``)."""
    if not isinstance(value, str) or _BIGINT_WIRE_RE.match(value) is None:
        raise NormalizationError(
            f'{field_name} must be an exact native BigInt string ("123n"), '
            f"got {value!r}"
        )
    return int(value[:-1])


def is_bigint_wire(value: object) -> bool:
    return isinstance(value, str) and _BIGINT_WIRE_RE.match(value) is not None


# ── Order side ───────────────────────────────────────────────────
# Verified against the live spec: ApiPerpetualsOrderToPlace.side is a numeric
# enum, 0 = bid (long), 1 = ask (short).  There is no "buy"/"sell" string form
# on the native surface; that spelling belongs to CCXT.


@dataclass(frozen=True)
class Side:
    BID: int = 0
    ASK: int = 1


def side_to_native(side: str | int) -> int:
    """Normalise a human side to the native numeric enum."""
    if isinstance(side, bool):
        raise NormalizationError("side must not be a bool")
    if isinstance(side, int):
        if side in (0, 1):
            return side
        raise NormalizationError(f"native side must be 0 (bid) or 1 (ask), got {side}")
    text = str(side).strip().lower()
    if text in {"buy", "bid", "long", "b"}:
        return Side.BID
    if text in {"sell", "ask", "short", "s"}:
        return Side.ASK
    raise NormalizationError(f"unknown order side: {side!r}")


def side_to_ccxt(side: str | int) -> str:
    return "buy" if side_to_native(side) == Side.BID else "sell"


# ── Instrument normalisation ─────────────────────────────────────


def normalise_instrument(symbol: str) -> str:
    """Strip venue-specific decoration from an upstream instrument name.

    Upstream strategy packages carry Hyperliquid spellings: HIP-3 builder-dex
    assets are prefixed (``xyz:GOLD``) and perp names may be suffixed
    (``BTC-PERP``, ``BTC/USDC:USDC``).  None of that means anything on
    Aftermath, where the market is addressed by an API-issued object id.  This
    reduces the upstream spelling to a bare base symbol which the registry then
    RESOLVES — the prefix is discarded, never re-pointed at an Aftermath venue.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise NormalizationError("instrument symbol must be a non-empty string")
    text = symbol.strip()
    if ":" in text and not text.startswith("0x"):
        head, _, tail = text.partition(":")
        # "BTC/USDC:USDC" -> the settlement suffix, not a dex prefix.
        text = head if "/" in head else tail
    if "/" in text:
        text = text.split("/", 1)[0]
    for suffix in ("-PERP", "_PERP", "-USD", "-USDC", "PERP"):
        if text.upper().endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text.strip().upper()
