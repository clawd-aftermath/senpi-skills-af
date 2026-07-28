"""Pure relaunch market/price response helpers for legacy DSL v4."""

from __future__ import annotations

from typing import Any


class PriceResolutionError(ValueError):
    """Raised when a market or human-denominated price cannot be resolved."""


def _market_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    live_rows = response.get("marketDatas")
    if isinstance(live_rows, list):
        return [row for row in live_rows if isinstance(row, dict)]

    fallback = response.get("markets")
    if isinstance(fallback, list):
        return [
            {"market": market, "metadata": {}}
            for market in fallback
            if isinstance(market, dict)
        ]
    return []


def resolve_market_id(response: dict[str, Any], asset: str) -> str:
    """Resolve one market ID deterministically from live or fallback shapes."""

    lookup = asset.split(":", 1)[-1].upper()
    matches: list[tuple[int, str]] = []

    for row in _market_rows(response):
        market = row.get("market", {})
        metadata = row.get("metadata", {})
        if not isinstance(market, dict) or not isinstance(metadata, dict):
            continue

        market_id = market.get("objectId") or market.get("marketId")
        if not market_id:
            continue

        metadata_symbol = str(metadata.get("symbol", "")).upper()
        base_symbol = str(
            market.get("marketParams", {}).get("baseAssetSymbol", "")
        ).upper()
        score = 0
        if metadata_symbol == lookup:
            score = 4
        elif base_symbol == lookup:
            score = 3
        elif base_symbol == f"{lookup}USD":
            score = 2
        elif metadata_symbol == f"{lookup}USD":
            score = 1
        if score:
            matches.append((score, str(market_id)))

    if not matches:
        raise PriceResolutionError(f"market id missing for asset {asset}")

    best_score = max(score for score, _ in matches)
    best_ids = {
        market_id for score, market_id in matches if score == best_score
    }
    if len(best_ids) != 1:
        raise PriceResolutionError(
            f"ambiguous market ids for asset {asset}: {sorted(best_ids)}"
        )
    return next(iter(best_ids))


def extract_human_mid_price(
    response: dict[str, Any],
    market_id: str,
) -> float:
    """Return the explicit market's human-denominated midPrice without scaling."""

    rows = response.get("marketsPrices")
    if not isinstance(rows, list):
        raise PriceResolutionError("marketsPrices missing from response")

    matches = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("marketId") == market_id
    ]
    if len(matches) != 1:
        raise PriceResolutionError(
            f"expected one price row for {market_id}, found {len(matches)}"
        )

    row = matches[0]
    try:
        mid_price = float(row["midPrice"])
    except (KeyError, TypeError, ValueError) as error:
        raise PriceResolutionError(
            f"invalid midPrice for market {market_id}"
        ) from error
    if mid_price <= 0:
        raise PriceResolutionError(
            f"non-positive midPrice for market {market_id}"
        )
    if mid_price > 1_000_000_000:
        raise PriceResolutionError(
            f"implausible human midPrice for market {market_id}"
        )

    references = []
    for key in ("basePrice", "markPrice"):
        try:
            value = float(row[key])
        except (KeyError, TypeError, ValueError):
            continue
        if value > 0:
            references.append(value)
    if not references:
        raise PriceResolutionError(
            f"human price reference missing for market {market_id}"
        )
    ratio = mid_price / references[0]
    if ratio < 1e-6 or ratio > 1e6:
        raise PriceResolutionError(
            f"midPrice unit mismatch for market {market_id}"
        )

    return mid_price
