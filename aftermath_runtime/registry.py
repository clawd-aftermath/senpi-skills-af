"""Fail-closed market discovery and capability checks."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from .errors import AmbiguousMarket, MarketUnavailable, NormalizationError
from .models import MarketSpec


@dataclass(frozen=True)
class MarketRegistry:
    markets: tuple[MarketSpec, ...]

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "MarketRegistry":
        rows = payload.get("marketDatas")
        if not isinstance(rows, list):
            # The pinned OpenAPI currently advertises ``orderbooks`` here while
            # the live V2 endpoint returns ``marketDatas``.  Orderbook rows do
            # not carry tick/lot/funding metadata, so accepting them would make
            # unit conversion guessy.  Fail closed until the contract converges.
            raise NormalizationError(
                "markets response requires marketDatas; orderbook-only OpenAPI shape "
                "cannot populate a safe market registry"
            )
        markets = tuple(MarketSpec.from_market_data(row) for row in rows)
        ids = [market.market_id for market in markets]
        if len(ids) != len(set(ids)):
            raise AmbiguousMarket("duplicate market IDs in market registry")
        return cls(markets)

    def resolve(self, symbol_or_id: str) -> MarketSpec:
        query = symbol_or_id.split(":", 1)[-1].upper()
        direct = [
            market
            for market in self.markets
            if market.market_id.lower() == symbol_or_id.lower()
        ]
        if len(direct) == 1:
            return direct[0]
        if re.fullmatch(r"0x[0-9a-fA-F]+", symbol_or_id):
            raise MarketUnavailable(f"no exact active Aftermath market ID {symbol_or_id!r}")
        scored: list[tuple[int, MarketSpec]] = []
        for market in self.markets:
            score = 0
            if market.symbol == query:
                score = 4
            elif market.base_asset_symbol == query:
                score = 3
            elif market.base_asset_symbol == f"{query}USD":
                score = 2
            elif market.symbol == f"{query}USD":
                score = 1
            if score:
                scored.append((score, market))
        if not scored:
            raise MarketUnavailable(f"no active Aftermath market for {symbol_or_id!r}")
        best_score = max(score for score, _ in scored)
        best = {market.market_id: market for score, market in scored if score == best_score}
        if len(best) != 1:
            raise AmbiguousMarket(
                f"ambiguous Aftermath market for {symbol_or_id!r}: {sorted(best)}"
            )
        return next(iter(best.values()))

    def require(self, symbol_or_id: str, capabilities: Iterable[str]) -> MarketSpec:
        market = self.resolve(symbol_or_id)
        missing = set(capabilities) - set(market.capabilities)
        if missing:
            raise MarketUnavailable(
                f"{symbol_or_id!r} lacks required capabilities: {sorted(missing)}"
            )
        return market
