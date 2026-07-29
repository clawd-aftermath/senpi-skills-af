"""Explicit B9/native integer codecs.

These helpers are fixtures for future execution work.  They do not construct,
sign, or submit an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Literal

from .errors import NormalizationError
from .models import MarketSpec, decimal_value

B9 = Decimal("0.000000001")


@dataclass(frozen=True)
class NativeCodec:
    market: MarketSpec
    price_unit: Decimal = B9
    size_unit: Decimal = B9

    def _quantized_native(
        self,
        human_value: Decimal | str | int | float,
        *,
        unit: Decimal,
        quantum: int,
        rounding: str,
        field_name: str,
    ) -> int:
        value = decimal_value(human_value, field_name, positive=True)
        # Direction-consistent rounding is required at both stages. Rounding to
        # nearest here could move a bid above the caller's limit before the
        # tick-floor step.
        unquantized = (value / unit).to_integral_value(rounding=rounding)
        native = int(unquantized)
        remainder = native % quantum
        if remainder:
            if rounding == ROUND_CEILING:
                native += quantum - remainder
            else:
                native -= remainder
        if native <= 0:
            raise NormalizationError(f"{field_name} is below the market quantum")
        return native

    def price_to_native(
        self, human_price: Decimal | str | int | float, side: Literal["buy", "sell"]
    ) -> int:
        if side not in {"buy", "sell"}:
            raise NormalizationError(f"unknown side: {side!r}")
        # Bids round down; asks round up.
        return self._quantized_native(
            human_price,
            unit=self.price_unit,
            quantum=self.market.tick_size_native,
            rounding=ROUND_FLOOR if side == "buy" else ROUND_CEILING,
            field_name="human_price",
        )

    def size_to_native(self, human_size: Decimal | str | int | float) -> int:
        return self._quantized_native(
            human_size,
            unit=self.size_unit,
            quantum=self.market.lot_size_native,
            rounding=ROUND_FLOOR,
            field_name="human_size",
        )

    def price_from_native(self, native_price: int) -> Decimal:
        if native_price <= 0 or native_price % self.market.tick_size_native:
            raise NormalizationError("native price is not positive and tick-aligned")
        return Decimal(native_price) * self.price_unit

    def size_from_native(self, native_size: int) -> Decimal:
        if native_size <= 0 or native_size % self.market.lot_size_native:
            raise NormalizationError("native size is not positive and lot-aligned")
        return Decimal(native_size) * self.size_unit
