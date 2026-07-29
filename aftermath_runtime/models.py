"""Typed, venue-neutral read models for Aftermath V2.

All public price and position fields are human-denominated.  Native integer
quantities remain explicitly named ``*_native`` so callers cannot accidentally
mix the two domains.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .errors import NormalizationError

# Denominations are derived from the pinned OpenAPI field descriptions.  This
# table is authoritative; magnitude is never used to guess a field's units.
FIELD_DENOMINATIONS: dict[tuple[str, str], str] = {
    ("/api/perpetuals/markets/prices", "basePrice"): "human_price",
    ("/api/perpetuals/markets/prices", "collateralPrice"): "human_price",
    ("/api/perpetuals/markets/prices", "markPrice"): "human_price",
    ("/api/perpetuals/markets/prices", "midPrice"): "human_price",
    ("/api/perpetuals/market/candle-history", "open"): "human_price",
    ("/api/perpetuals/market/candle-history", "high"): "human_price",
    ("/api/perpetuals/market/candle-history", "low"): "human_price",
    ("/api/perpetuals/market/candle-history", "close"): "human_price",
    ("/api/perpetuals/market/candle-history", "volume"): "human_size",
    ("/api/perpetuals/accounts/positions", "baseAssetAmount"): "human_size",
    ("/api/perpetuals/accounts/positions", "entryPrice"): "human_price",
    ("/api/perpetuals/accounts/positions", "liquidationPrice"): "human_price",
    ("/api/perpetuals/accounts/positions", "pendingOrders.currentSize"): "native_lots",
    ("/api/perpetuals/accounts/positions", "pendingOrders.initialSize"): "native_lots",
    ("/api/perpetuals/markets", "marketParams.tickSize"): "native_quote_units",
    ("/api/perpetuals/markets", "marketParams.lotSize"): "native_base_units",
}


def require_denomination(endpoint: str, field_name: str, expected: str) -> None:
    actual = FIELD_DENOMINATIONS.get((endpoint, field_name))
    if actual != expected:
        raise NormalizationError(
            f"no {expected} denomination contract for {endpoint} {field_name}"
        )


def decimal_value(value: Any, field_name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise NormalizationError(f"{field_name} must be numeric, not boolean")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise NormalizationError(f"{field_name} is not numeric: {value!r}") from exc
    if not result.is_finite():
        raise NormalizationError(f"{field_name} must be finite")
    if positive and result <= 0:
        raise NormalizationError(f"{field_name} must be positive")
    return result


def protocol_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise NormalizationError(f"{field_name} must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        raw = value[:-1] if value.endswith("n") else value
        if not raw.isdigit():
            raise NormalizationError(f"{field_name} is not a protocol integer: {value!r}")
        result = int(raw)
    else:
        raise NormalizationError(f"{field_name} is not a protocol integer: {value!r}")
    if result < minimum:
        raise NormalizationError(f"{field_name} must be >= {minimum}")
    return result


def text_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NormalizationError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class MarketSpec:
    market_id: str
    package_id: str
    symbol: str
    base_asset_symbol: str
    collateral_symbol: str
    collateral_coin_type: str
    tick_size_native: int
    lot_size_native: int
    scaling_factor: Decimal
    funding_interval_ms: int
    funding_period_ms: int
    min_order_usd: Decimal
    capabilities: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {"prices", "candles", "funding", "account", "positions", "open_orders"}
        )
    )

    @classmethod
    def from_market_data(cls, row: Mapping[str, Any]) -> "MarketSpec":
        market = row.get("market")
        metadata = row.get("metadata")
        if not isinstance(market, Mapping) or not isinstance(metadata, Mapping):
            raise NormalizationError("marketDatas row requires market and metadata objects")
        params = market.get("marketParams")
        if not isinstance(params, Mapping):
            raise NormalizationError("market.marketParams must be an object")
        return cls(
            market_id=text_value(
                market.get("objectId") or market.get("marketId"), "market.objectId"
            ),
            package_id=text_value(market.get("packageId"), "market.packageId"),
            symbol=text_value(metadata.get("symbol"), "metadata.symbol").upper(),
            base_asset_symbol=text_value(
                params.get("baseAssetSymbol"), "marketParams.baseAssetSymbol"
            ).upper(),
            collateral_symbol=text_value(
                metadata.get("collateralSymbol"), "metadata.collateralSymbol"
            ).upper(),
            collateral_coin_type=text_value(
                market.get("collateralCoinType"), "market.collateralCoinType"
            ),
            tick_size_native=protocol_int(
                params.get("tickSize"), "marketParams.tickSize", minimum=1
            ),
            lot_size_native=protocol_int(
                params.get("lotSize"), "marketParams.lotSize", minimum=1
            ),
            scaling_factor=decimal_value(
                params.get("scalingFactor"), "marketParams.scalingFactor", positive=True
            ),
            funding_interval_ms=protocol_int(
                params.get("fundingFrequencyMs"),
                "marketParams.fundingFrequencyMs",
                minimum=1,
            ),
            funding_period_ms=protocol_int(
                params.get("fundingPeriodMs"), "marketParams.fundingPeriodMs", minimum=1
            ),
            min_order_usd=decimal_value(
                params.get("minOrderUsdValue"),
                "marketParams.minOrderUsdValue",
                positive=True,
            ),
        )


@dataclass(frozen=True)
class PriceSnapshot:
    market_id: str
    base_price: Decimal
    collateral_price: Decimal
    mark_price: Decimal
    mid_price: Decimal | None

    @classmethod
    def from_api(cls, row: Mapping[str, Any]) -> "PriceSnapshot":
        endpoint = "/api/perpetuals/markets/prices"
        for name in ("basePrice", "collateralPrice", "markPrice", "midPrice"):
            require_denomination(endpoint, name, "human_price")
        result = cls(
            market_id=text_value(row.get("marketId"), "marketId"),
            base_price=decimal_value(row.get("basePrice"), "basePrice", positive=True),
            collateral_price=decimal_value(
                row.get("collateralPrice"), "collateralPrice", positive=True
            ),
            mark_price=decimal_value(row.get("markPrice"), "markPrice", positive=True),
            mid_price=(
                None
                if row.get("midPrice") is None
                else decimal_value(row.get("midPrice"), "midPrice", positive=True)
            ),
        )
        # Unit identity comes from FIELD_DENOMINATIONS, not value magnitude.
        # The ratio check is only a tripwire for a mixed-unit row.
        values = [result.base_price, result.mark_price]
        if result.mid_price is not None:
            values.append(result.mid_price)
        ratio = max(values) / min(values)
        if ratio > Decimal("1000000"):
            raise NormalizationError("price row contains incompatible units")
        return result


@dataclass(frozen=True)
class Candle:
    timestamp_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @classmethod
    def from_api(cls, row: Mapping[str, Any]) -> "Candle":
        endpoint = "/api/perpetuals/market/candle-history"
        for name in ("open", "high", "low", "close"):
            require_denomination(endpoint, name, "human_price")
        require_denomination(endpoint, "volume", "human_size")
        candle = cls(
            timestamp_ms=protocol_int(row.get("timestamp"), "timestamp"),
            open=decimal_value(row.get("open"), "open", positive=True),
            high=decimal_value(row.get("high"), "high", positive=True),
            low=decimal_value(row.get("low"), "low", positive=True),
            close=decimal_value(row.get("close"), "close", positive=True),
            volume=decimal_value(row.get("volume"), "volume"),
        )
        if candle.volume < 0:
            raise NormalizationError("candle volume cannot be negative")
        if candle.high < max(candle.open, candle.close, candle.low):
            raise NormalizationError("candle high is below an OHLC value")
        if candle.low > min(candle.open, candle.close, candle.high):
            raise NormalizationError("candle low is above an OHLC value")
        return candle

    def as_scanner_dict(self) -> dict[str, str | int]:
        """Return upstream scanner's canonical short-key candle shape."""
        return {
            "t": self.timestamp_ms,
            "o": str(self.open),
            "h": str(self.high),
            "l": str(self.low),
            "c": str(self.close),
            "v": str(self.volume),
        }


@dataclass(frozen=True)
class FundingPoint:
    market_id: str
    timestamp_ms: int
    event_timestamp_ms: int
    long_rate: Decimal
    short_rate: Decimal
    cumulative_long_rate: Decimal
    cumulative_short_rate: Decimal
    tx_digest: str
    interval_ms: int

    @classmethod
    def from_api(cls, row: Mapping[str, Any], *, interval_ms: int) -> "FundingPoint":
        return cls(
            market_id=text_value(row.get("marketId"), "marketId"),
            timestamp_ms=protocol_int(row.get("timestamp"), "timestamp"),
            event_timestamp_ms=protocol_int(
                row.get("eventTimestamp"), "eventTimestamp"
            ),
            long_rate=decimal_value(row.get("longFundingRate"), "longFundingRate"),
            short_rate=decimal_value(row.get("shortFundingRate"), "shortFundingRate"),
            cumulative_long_rate=decimal_value(
                row.get("cumulativeLongFundingRate"), "cumulativeLongFundingRate"
            ),
            cumulative_short_rate=decimal_value(
                row.get("cumulativeShortFundingRate"), "cumulativeShortFundingRate"
            ),
            tx_digest=text_value(row.get("txDigest"), "txDigest"),
            interval_ms=interval_ms,
        )


@dataclass(frozen=True)
class AccountCap:
    account_id: int
    capability_id: str
    account_object_id: str
    wallet_address: str
    collateral_coin_type: str
    collateral_native: int
    is_agent: bool

    @classmethod
    def from_api(cls, row: Mapping[str, Any]) -> "AccountCap":
        is_agent = row.get("isAgent")
        if not isinstance(is_agent, bool):
            raise NormalizationError("isAgent must be boolean")
        return cls(
            account_id=protocol_int(row.get("accountId"), "accountId"),
            capability_id=text_value(row.get("objectId"), "objectId"),
            account_object_id=text_value(row.get("accountObjectId"), "accountObjectId"),
            wallet_address=text_value(row.get("walletAddress"), "walletAddress"),
            collateral_coin_type=text_value(
                row.get("collateralCoinType"), "collateralCoinType"
            ),
            collateral_native=protocol_int(row.get("collateral"), "collateral"),
            is_agent=is_agent,
        )


@dataclass(frozen=True)
class PendingOrderRef:
    order_id: int
    client_order_id: int | None
    side: str
    current_size_native: int
    initial_size_native: int

    @classmethod
    def from_api(cls, row: Mapping[str, Any]) -> "PendingOrderRef":
        endpoint = "/api/perpetuals/accounts/positions"
        require_denomination(endpoint, "pendingOrders.currentSize", "native_lots")
        require_denomination(endpoint, "pendingOrders.initialSize", "native_lots")
        side_raw = protocol_int(row.get("side"), "side")
        if side_raw not in (0, 1):
            raise NormalizationError(f"unknown pending-order side: {side_raw}")
        return cls(
            order_id=protocol_int(row.get("orderId"), "orderId"),
            client_order_id=(
                None
                if row.get("clientOrderId") is None
                else protocol_int(row.get("clientOrderId"), "clientOrderId")
            ),
            side="buy" if side_raw == 0 else "sell",
            current_size_native=protocol_int(row.get("currentSize"), "currentSize"),
            initial_size_native=protocol_int(row.get("initialSize"), "initialSize"),
        )


@dataclass(frozen=True)
class PositionSnapshot:
    market_id: str
    base_amount: Decimal
    notional_amount: Decimal
    collateral: Decimal
    collateral_usd: Decimal
    free_margin_usd: Decimal
    leverage: Decimal
    margin_ratio: Decimal
    entry_price: Decimal
    liquidation_price: Decimal
    unrealized_pnl_usd: Decimal
    unrealized_funding_usd: Decimal
    pending_orders: tuple[PendingOrderRef, ...]

    @classmethod
    def from_api(cls, row: Mapping[str, Any]) -> "PositionSnapshot":
        endpoint = "/api/perpetuals/accounts/positions"
        require_denomination(endpoint, "baseAssetAmount", "human_size")
        require_denomination(endpoint, "entryPrice", "human_price")
        require_denomination(endpoint, "liquidationPrice", "human_price")
        raw_orders = row.get("pendingOrders")
        if not isinstance(raw_orders, list):
            raise NormalizationError("position.pendingOrders must be an array")
        return cls(
            market_id=text_value(row.get("marketId"), "position.marketId"),
            base_amount=decimal_value(row.get("baseAssetAmount"), "baseAssetAmount"),
            notional_amount=decimal_value(
                row.get("quoteAssetNotionalAmount"), "quoteAssetNotionalAmount"
            ),
            collateral=decimal_value(row.get("collateral"), "collateral"),
            collateral_usd=decimal_value(row.get("collateralUsd"), "collateralUsd"),
            free_margin_usd=decimal_value(row.get("freeMarginUsd"), "freeMarginUsd"),
            leverage=decimal_value(row.get("leverage"), "leverage"),
            margin_ratio=decimal_value(row.get("marginRatio"), "marginRatio"),
            entry_price=decimal_value(row.get("entryPrice"), "entryPrice"),
            liquidation_price=decimal_value(
                row.get("liquidationPrice"), "liquidationPrice"
            ),
            unrealized_pnl_usd=decimal_value(
                row.get("unrealizedPnlUsd"), "unrealizedPnlUsd"
            ),
            unrealized_funding_usd=decimal_value(
                row.get("unrealizedFundingsUsd"), "unrealizedFundingsUsd"
            ),
            pending_orders=tuple(PendingOrderRef.from_api(x) for x in raw_orders),
        )


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: int
    total_equity_usd: Decimal
    available_collateral: Decimal
    available_collateral_usd: Decimal
    total_unrealized_funding_usd: Decimal
    total_unrealized_pnl_usd: Decimal
    positions: tuple[PositionSnapshot, ...]

    @classmethod
    def from_api(cls, row: Mapping[str, Any]) -> "AccountSnapshot":
        raw_positions = row.get("positions")
        if not isinstance(raw_positions, list):
            raise NormalizationError("account.positions must be an array")
        return cls(
            account_id=protocol_int(row.get("accountId"), "accountId"),
            total_equity_usd=decimal_value(row.get("totalEquityUsd"), "totalEquityUsd"),
            available_collateral=decimal_value(
                row.get("availableCollateral"), "availableCollateral"
            ),
            available_collateral_usd=decimal_value(
                row.get("availableCollateralUsd"), "availableCollateralUsd"
            ),
            total_unrealized_funding_usd=decimal_value(
                row.get("totalUnrealizedFundingsUsd"), "totalUnrealizedFundingsUsd"
            ),
            total_unrealized_pnl_usd=decimal_value(
                row.get("totalUnrealizedPnlUsd"), "totalUnrealizedPnlUsd"
            ),
            positions=tuple(PositionSnapshot.from_api(x) for x in raw_positions),
        )


@dataclass(frozen=True)
class OpenOrder:
    order_id: str
    market_symbol: str
    side: str
    price: Decimal
    amount: Decimal
    filled: Decimal
    remaining: Decimal
    status: str
    client_order_id: str | None

    @classmethod
    def from_ccxt(cls, row: Mapping[str, Any]) -> "OpenOrder":
        side = text_value(row.get("side"), "order.side").lower()
        if side not in {"buy", "sell"}:
            raise NormalizationError(f"unsupported order side: {side!r}")
        return cls(
            order_id=text_value(row.get("id"), "order.id"),
            market_symbol=text_value(row.get("symbol"), "order.symbol"),
            side=side,
            price=decimal_value(row.get("price"), "order.price"),
            amount=decimal_value(row.get("amount"), "order.amount"),
            filled=decimal_value(row.get("filled"), "order.filled"),
            remaining=decimal_value(row.get("remaining"), "order.remaining"),
            status=text_value(row.get("status"), "order.status"),
            client_order_id=(
                None if row.get("clientOrderId") is None else str(row["clientOrderId"])
            ),
        )
