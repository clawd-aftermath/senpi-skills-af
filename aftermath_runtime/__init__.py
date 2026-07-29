"""Read-only Aftermath V2 venue overlay.

This package intentionally contains no signing, submission, or order-placement
implementation.  It is safe to import from strategy scanners.
"""

from .codec import B9, NativeCodec
from .errors import (
    AmbiguousMarket,
    ContractError,
    ContractDriftError,
    MarketUnavailable,
    NormalizationError,
    WriteDenied,
)
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
)
from .registry import MarketRegistry
from .stream import CANDLE_STREAM_PATH, SnapshotStreamState, market_candles_subscription
from .transport import FixtureTransport, JsonTransport, UrllibReadTransport
from .venue import AftermathVenue

__all__ = [
    "AccountCap",
    "AccountSnapshot",
    "AftermathVenue",
    "AmbiguousMarket",
    "B9",
    "Candle",
    "CANDLE_STREAM_PATH",
    "ContractError",
    "ContractDriftError",
    "FixtureTransport",
    "FundingPoint",
    "JsonTransport",
    "MarketRegistry",
    "MarketSpec",
    "MarketUnavailable",
    "NativeCodec",
    "NormalizationError",
    "OpenOrder",
    "PositionSnapshot",
    "PriceSnapshot",
    "SnapshotStreamState",
    "UrllibReadTransport",
    "WriteDenied",
    "assert_runtime_enablement",
    "market_candles_subscription",
]
