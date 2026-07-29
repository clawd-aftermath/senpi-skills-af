"""Typed read-only Aftermath V2 venue."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import time
from collections.abc import Callable
from typing import Any, Mapping, Sequence

from .errors import ContractError, MarketUnavailable, NormalizationError, WriteDenied
from .gate import assert_runtime_enablement
from .models import (
    AccountCap,
    AccountSnapshot,
    Candle,
    FundingPoint,
    MarketSpec,
    OpenOrder,
    PositionSnapshot,
    PriceSnapshot,
    protocol_int,
)
from .registry import MarketRegistry
from .transport import JsonTransport


def reject_error_union(payload: Any, *, endpoint: str) -> Any:
    """Reject HTTP-200 error unions used by preview/build-style endpoints."""
    if isinstance(payload, Mapping):
        if payload.get("success") is False:
            raise ContractError(f"{endpoint} returned success=false")
        for key in ("error", "errors", "errorMessage"):
            if key in payload and payload[key] not in (None, "", [], {}):
                raise ContractError(f"{endpoint} returned an error payload: {key}")
    return payload


def _object(payload: Any, endpoint: str) -> Mapping[str, Any]:
    reject_error_union(payload, endpoint=endpoint)
    if not isinstance(payload, Mapping):
        raise ContractError(f"{endpoint} response must be an object")
    return payload


def _array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{field_name} must be an array")
    return value


def _resolution_ms(resolution: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)([mhd])", resolution)
    if not match:
        raise NormalizationError(f"unsupported candle resolution: {resolution!r}")
    multiplier = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}[match.group(2)]
    return int(match.group(1)) * multiplier


@dataclass
class AftermathVenue:
    transport: JsonTransport
    now_ms: Callable[[], int] = field(
        default=lambda: int(time.time() * 1000), repr=False
    )
    runtime_config: Mapping[str, Any] = field(
        default_factory=lambda: {"mode": "shadow", "write_policy": "deny"},
        repr=False,
    )
    _registry: MarketRegistry | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        assert_runtime_enablement(self.runtime_config)

    def refresh_markets(self) -> MarketRegistry:
        payload = _object(
            self.transport.post("/api/perpetuals/markets", {}),
            "/api/perpetuals/markets",
        )
        self._registry = MarketRegistry.from_api(payload)
        return self._registry

    @property
    def registry(self) -> MarketRegistry:
        return self._registry or self.refresh_markets()

    def list_markets(self) -> tuple[MarketSpec, ...]:
        return self.registry.markets

    def require_market(
        self, symbol_or_id: str, capabilities: Sequence[str] = ()
    ) -> MarketSpec:
        return self.registry.require(symbol_or_id, capabilities)

    def get_prices(self, markets: Sequence[str]) -> dict[str, PriceSnapshot]:
        resolved = [self.require_market(market, ("prices",)) for market in markets]
        market_ids = [market.market_id for market in resolved]
        endpoint = "/api/perpetuals/markets/prices"
        payload = _object(self.transport.post(endpoint, {"marketIds": market_ids}), endpoint)
        rows = _array(payload.get("marketsPrices"), "marketsPrices")
        normalized = [PriceSnapshot.from_api(row) for row in rows]
        keyed = {price.market_id: price for price in normalized}
        if len(keyed) != len(normalized):
            raise NormalizationError("duplicate market IDs in price response")
        missing = set(market_ids) - set(keyed)
        if missing:
            raise MarketUnavailable(f"missing requested price rows: {sorted(missing)}")
        return keyed

    def get_candles(
        self,
        market: str,
        resolution: str,
        from_timestamp_ms: int,
        to_timestamp_ms: int,
    ) -> tuple[Candle, ...]:
        spec = self.require_market(market, ("candles",))
        if not isinstance(resolution, str) or not resolution:
            raise NormalizationError("resolution must be a non-empty string")
        interval_ms = _resolution_ms(resolution)
        start = protocol_int(from_timestamp_ms, "from_timestamp_ms")
        requested_end = protocol_int(to_timestamp_ms, "to_timestamp_ms")
        end = min(requested_end, protocol_int(self.now_ms(), "now_ms"))
        if start >= end:
            raise NormalizationError("candle range must have from < to")
        endpoint = "/api/perpetuals/market/candle-history"
        payload = _object(
            self.transport.post(
                endpoint,
                {
                    "marketId": spec.market_id,
                    "resolution": resolution,
                    "fromTimestamp": start,
                    "toTimestamp": end,
                },
            ),
            endpoint,
        )
        rows = _array(payload.get("candles"), "candles")
        normalized = tuple(Candle.from_api(row) for row in rows)
        # Candle timestamps are bucket starts. Never feed a still-open bucket
        # into a scanner: it changes after the signal has been scored.
        candles = tuple(
            candle
            for candle in normalized
            if candle.timestamp_ms + interval_ms <= end
        )
        if any(
            candles[index].timestamp_ms >= candles[index + 1].timestamp_ms
            for index in range(len(candles) - 1)
        ):
            raise NormalizationError("candles must be strictly time-ordered")
        return candles

    def get_funding(
        self,
        market: str,
        from_timestamp_ms: int,
        to_timestamp_ms: int,
        *,
        limit: int | None = None,
    ) -> tuple[FundingPoint, ...]:
        spec = self.require_market(market, ("funding",))
        start = protocol_int(from_timestamp_ms, "from_timestamp_ms")
        end = protocol_int(to_timestamp_ms, "to_timestamp_ms")
        if start >= end:
            raise NormalizationError("funding range must have from < to")
        request: dict[str, Any] = {
            "marketId": spec.market_id,
            "fromTimestamp": start,
            "toTimestamp": end,
        }
        if limit is not None:
            request["limit"] = protocol_int(limit, "limit", minimum=1)
        endpoint = "/api/perpetuals/market/funding-history"
        payload = _object(self.transport.post(endpoint, request), endpoint)
        rows = _array(payload.get("history"), "history")
        points = tuple(
            FundingPoint.from_api(row, interval_ms=spec.funding_interval_ms)
            for row in rows
        )
        if any(point.market_id != spec.market_id for point in points):
            raise NormalizationError("funding response contains an unexpected market ID")
        return points

    def get_account_caps(self, account_ids: Sequence[int]) -> dict[int, AccountCap]:
        ids = [protocol_int(value, "account_id") for value in account_ids]
        endpoint = "/api/perpetuals/accounts"
        payload = _object(self.transport.post(endpoint, {"accountIds": ids}), endpoint)
        rows = _array(payload.get("accountCaps"), "accountCaps")
        caps = [AccountCap.from_api(row) for row in rows]
        keyed = {cap.account_id: cap for cap in caps}
        if len(keyed) != len(caps):
            raise NormalizationError("duplicate account IDs in account-cap response")
        missing = set(ids) - set(keyed)
        if missing:
            raise NormalizationError(f"missing requested account caps: {sorted(missing)}")
        return keyed

    def get_account(self, account_id: int) -> AccountSnapshot:
        numeric_id = protocol_int(account_id, "account_id")
        endpoint = "/api/perpetuals/accounts/positions"
        payload = _object(
            self.transport.post(endpoint, {"accountIds": [numeric_id]}), endpoint
        )
        rows = _array(payload.get("accounts"), "accounts")
        accounts = [AccountSnapshot.from_api(row) for row in rows]
        matches = [account for account in accounts if account.account_id == numeric_id]
        if len(matches) != 1:
            raise NormalizationError(
                f"expected exactly one account {numeric_id}, found {len(matches)}"
            )
        return matches[0]

    def get_positions(
        self, account_id: int, markets: Sequence[str] = ()
    ) -> tuple[PositionSnapshot, ...]:
        numeric_id = protocol_int(account_id, "account_id")
        specs = [self.require_market(market, ("positions",)) for market in markets]
        request: dict[str, Any] = {"accountIds": [numeric_id]}
        if specs:
            request["marketIds"] = [market.market_id for market in specs]
        endpoint = "/api/perpetuals/accounts/positions"
        payload = _object(self.transport.post(endpoint, request), endpoint)
        rows = _array(payload.get("accounts"), "accounts")
        accounts = [AccountSnapshot.from_api(row) for row in rows]
        matches = [account for account in accounts if account.account_id == numeric_id]
        if len(matches) != 1:
            raise NormalizationError(
                f"expected exactly one account {numeric_id}, found {len(matches)}"
            )
        positions = matches[0].positions
        if specs:
            allowed = {market.market_id for market in specs}
            if any(position.market_id not in allowed for position in positions):
                raise NormalizationError("positions response ignored requested market filter")
        return positions

    def get_open_orders(self, account_id: int, market: str) -> tuple[OpenOrder, ...]:
        numeric_id = protocol_int(account_id, "account_id")
        spec = self.require_market(market, ("open_orders",))
        endpoint = "/api/ccxt/myPendingOrders"
        payload = reject_error_union(
            self.transport.post(
                endpoint, {"accountNumber": numeric_id, "chId": spec.market_id}
            ),
            endpoint=endpoint,
        )
        rows = _array(payload, "myPendingOrders")
        return tuple(OpenOrder.from_ccxt(row) for row in rows)

    def submit_order_intent(self, *_args: Any, **_kwargs: Any) -> None:
        raise WriteDenied(
            "AftermathVenue is read-only; execution/PTB/signing is not implemented"
        )
