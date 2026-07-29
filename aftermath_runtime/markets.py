"""Market discovery from ``/api/perpetuals/all-markets``.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

Verified contract:

* ``POST /api/perpetuals/all-markets`` **requires** ``{collateralCoinType}``
  and answers ``{"markets": [...]}`` — an object, NOT a bare array.
* each entry carries ``objectId`` (the marketId), ``packageId``,
  ``collateralCoinType``, ``marketParams``, ``marketState``,
  ``collateralPrice``, ``indexPrice``, ``estimatedFundingRate`` and
  ``nextFundingTimestampMs``.
* ``marketParams.baseAssetSymbol`` is the human ticker.  It is NOT the
  marketId; Aftermath validates marketIds strictly and they are Sui object ids.
* ``marketParams.lotSize`` / ``tickSize`` / ``maxPendingOrders`` and
  ``nextFundingTimestampMs`` are native BigInt fields serialised as ``"...n"``.

**Zero markets is EXPECTED before the relaunch.**  An empty registry warns; it
never raises.  Resolving a specific symbol against an empty registry raises,
because returning a fabricated market would be far worse.

Removed in v3.0.0 and deliberately not read here: ``gasPriceTwapPeriodMs``,
``forceCancelFee``, ``gasPriceTakerFee``, ``zScoreThreshold`` (superseded by
``priorityTakerFee``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from .errors import AmbiguousMarket, ContractError, MarketUnavailable, NormalizationError
from .ids import MarketId, normalise_instrument

ALL_MARKETS_PATH = "/api/perpetuals/all-markets"

_REMOVED_V3_MARKET_PARAM_FIELDS = (
    "gasPriceTwapPeriodMs",
    "forceCancelFee",
    "gasPriceTakerFee",
    "zScoreThreshold",
)


def _bigint(value: Any, field_name: str) -> int:
    """Accept the documented ``"...n"`` form, and a plain int if the API sends one."""
    if isinstance(value, bool):
        raise NormalizationError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value[:-1] if value.endswith("n") else value
        if text.isdigit():
            return int(text)
    raise NormalizationError(f"{field_name} is not a native integer: {value!r}")


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise NormalizationError(f"{field_name} must be numeric: {value!r}")
    try:
        return float(Decimal(str(value)))
    except Exception as exc:  # noqa: BLE001
        raise NormalizationError(f"{field_name} is not numeric: {value!r}") from exc


@dataclass(frozen=True)
class Market:
    """One Aftermath perpetual market, normalised."""

    market_id: MarketId
    package_id: str
    symbol: str
    collateral_coin_type: str
    lot_size_native: int
    tick_size_native: int
    max_pending_orders: int
    margin_ratio_initial: float
    margin_ratio_maintenance: float
    maker_fee: float
    taker_fee: float
    min_order_usd_value: float
    index_price: float
    collateral_price: float
    estimated_funding_rate: float
    next_funding_timestamp_ms: int
    funding_frequency_ms: int
    funding_period_ms: int
    open_interest: float
    priority_taker_fee: float | None
    raw: Mapping[str, Any]

    @property
    def max_leverage(self) -> float:
        """Derived from the initial margin ratio; there is no leverage field."""
        if self.margin_ratio_initial <= 0:
            raise NormalizationError("marginRatioInitial must be positive")
        return 1.0 / self.margin_ratio_initial

    @classmethod
    def from_api(cls, row: Mapping[str, Any]) -> "Market":
        if not isinstance(row, Mapping):
            raise ContractError("all-markets row must be an object")
        params = row.get("marketParams")
        state = row.get("marketState")
        if not isinstance(params, Mapping) or not isinstance(state, Mapping):
            raise ContractError("market row requires marketParams and marketState")
        for removed in _REMOVED_V3_MARKET_PARAM_FIELDS:
            if removed in params:
                # Not fatal, but it means the host is pre-v3.  Say so loudly.
                raise ContractError(
                    f"marketParams carries {removed!r}, removed in v3.0.0 — the "
                    "API this runtime is talking to is not the v3 surface"
                )
        object_id = row.get("objectId")
        if not isinstance(object_id, str) or not object_id:
            raise ContractError("market row requires objectId")
        symbol = params.get("baseAssetSymbol")
        if not isinstance(symbol, str) or not symbol:
            raise ContractError("marketParams requires baseAssetSymbol")
        return cls(
            market_id=MarketId(object_id),
            package_id=str(row.get("packageId", "")),
            symbol=symbol.upper(),
            collateral_coin_type=str(row.get("collateralCoinType", "")),
            lot_size_native=_bigint(params.get("lotSize"), "lotSize"),
            tick_size_native=_bigint(params.get("tickSize"), "tickSize"),
            max_pending_orders=_bigint(
                params.get("maxPendingOrders"), "maxPendingOrders"
            ),
            margin_ratio_initial=_number(
                params.get("marginRatioInitial"), "marginRatioInitial"
            ),
            margin_ratio_maintenance=_number(
                params.get("marginRatioMaintenance"), "marginRatioMaintenance"
            ),
            maker_fee=_number(params.get("makerFee"), "makerFee"),
            taker_fee=_number(params.get("takerFee"), "takerFee"),
            min_order_usd_value=_number(
                params.get("minOrderUsdValue"), "minOrderUsdValue"
            ),
            index_price=_number(row.get("indexPrice"), "indexPrice"),
            collateral_price=_number(row.get("collateralPrice"), "collateralPrice"),
            estimated_funding_rate=_number(
                row.get("estimatedFundingRate"), "estimatedFundingRate"
            ),
            next_funding_timestamp_ms=_bigint(
                row.get("nextFundingTimestampMs"), "nextFundingTimestampMs"
            ),
            funding_frequency_ms=_bigint(
                params.get("fundingFrequencyMs"), "fundingFrequencyMs"
            ),
            funding_period_ms=_bigint(params.get("fundingPeriodMs"), "fundingPeriodMs"),
            open_interest=_number(state.get("openInterest"), "openInterest"),
            priority_taker_fee=(
                _number(params["priorityTakerFee"], "priorityTakerFee")
                if params.get("priorityTakerFee") is not None
                else None
            ),
            raw=row,
        )


@dataclass(frozen=True)
class MarketCatalog:
    """The resolved market universe.

    Deterministic ordering is guaranteed by the API (markets sort by symbol) and
    is preserved here rather than re-sorted blindly.
    """

    markets: tuple[Market, ...]
    collateral_coin_type: str

    @classmethod
    def from_api(
        cls, payload: Any, *, collateral_coin_type: str
    ) -> "MarketCatalog":
        if not isinstance(payload, Mapping):
            raise ContractError(
                f"{ALL_MARKETS_PATH} must answer an object; a bare array means "
                "the wrong endpoint or the wrong API version"
            )
        rows = payload.get("markets")
        if rows is None:
            raise ContractError(f"{ALL_MARKETS_PATH} response has no 'markets' key")
        if not isinstance(rows, list):
            raise ContractError(f"{ALL_MARKETS_PATH} 'markets' must be an array")
        markets = tuple(Market.from_api(row) for row in rows)
        ids = [m.market_id.value for m in markets]
        if len(ids) != len(set(ids)):
            raise AmbiguousMarket("duplicate marketIds in all-markets response")
        return cls(markets, collateral_coin_type)

    @property
    def is_empty(self) -> bool:
        return not self.markets

    def symbols(self) -> tuple[str, ...]:
        return tuple(m.symbol for m in self.markets)

    def resolve(self, symbol_or_id: str) -> Market:
        """Resolve an upstream instrument name to an Aftermath market.

        Upstream decoration (HIP-3 ``xyz:`` prefixes, ``-PERP`` suffixes,
        ``BTC/USDC:USDC`` spellings) is stripped, never re-pointed.  A market id
        matches exactly or not at all.
        """
        if not isinstance(symbol_or_id, str) or not symbol_or_id.strip():
            raise MarketUnavailable("instrument must be a non-empty string")
        raw = symbol_or_id.strip()
        for market in self.markets:
            if market.market_id.value == raw:
                return market
        if raw.startswith("0x"):
            raise MarketUnavailable(
                f"no active Aftermath market with id {raw!r}"
            )
        query = normalise_instrument(raw)
        matches = [m for m in self.markets if m.symbol == query]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AmbiguousMarket(
                f"{symbol_or_id!r} matches {len(matches)} Aftermath markets"
            )
        if self.is_empty:
            raise MarketUnavailable(
                f"no Aftermath markets are live yet, so {symbol_or_id!r} cannot "
                "be resolved. This is expected before the relaunch."
            )
        raise MarketUnavailable(
            f"no active Aftermath market for {symbol_or_id!r} "
            f"(available: {', '.join(self.symbols()) or 'none'})"
        )

    def resolve_many(self, instruments: Iterable[str]) -> tuple[Market, ...]:
        return tuple(self.resolve(item) for item in instruments)

    def try_resolve(self, symbol_or_id: str) -> Market | None:
        try:
            return self.resolve(symbol_or_id)
        except MarketUnavailable:
            return None


def all_markets_request(collateral_coin_type: str) -> dict[str, Any]:
    """``POST /api/perpetuals/all-markets`` requires ``{collateralCoinType}``."""
    if not isinstance(collateral_coin_type, str) or not collateral_coin_type:
        raise NormalizationError(
            "all-markets requires an explicit collateralCoinType"
        )
    return {"collateralCoinType": collateral_coin_type}


def prices_request(markets: Sequence[Market]) -> dict[str, Any]:
    return {"marketIds": [str(m.market_id) for m in markets]}
