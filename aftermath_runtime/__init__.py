"""Aftermath V2 execution runtime for the Senpi strategy packages.

ONE adapter (:class:`AftermathAdapter`) presents the upstream MCP tool surface
and serves it entirely from Aftermath V2, so every strategy package runs
without being individually ported.  Hyperliquid is removed from the execution
path — not proxied underneath it.

This package **never signs, submits, or broadcasts**.  Transaction builders
stop at an inspected transaction, and no submit route appears in any transport
allowlist.  It is safe to import from strategy scanners.
"""

from .accounts import AccountCapability, select_account
from .adapter import AftermathAdapter
from .codec import B9, NativeCodec
from .config import (
    DEFAULT_API_BASE_URL,
    DEFAULT_COLLATERAL_COIN_TYPE,
    RuntimeConfig,
    api_base_url,
    assert_not_retired_host,
)
from .errors import (
    AmbiguousMarket,
    CapabilityUnavailable,
    CircuitBreakerTripped,
    ConfigError,
    ContractError,
    ContractDriftError,
    InspectionFailed,
    MarketUnavailable,
    NormalizationError,
    PreviewRejected,
    WriteDenied,
)
from .execution import AccountRef, ExecutionClient, OrderToPlace, encode_bigints
from .gas import GAS_MODES, GasCheck, GasConfig, check_gas_mode, parse_gas_mode
from .gate import assert_runtime_enablement
from .ids import (
    AccountCapId,
    AccountNumber,
    MarketId,
    NativeAccountId,
    SuiAddress,
    from_bigint_wire,
    normalise_instrument,
    to_bigint_wire,
)
from .markets import Market, MarketCatalog
from .mock import MockAftermathAdapter
from .ptb import (
    InspectedTx,
    PreviewError,
    PreviewOk,
    PtbPipeline,
    TxIntent,
    inspect,
    parse_preview,
    reconcile,
    sign_inspected,
)
from .safety import (
    BotState,
    CircuitBreaker,
    HardLimits,
    KillSwitch,
    SerialGate,
    ShutdownHandler,
    SoftLimits,
    assess_margin_health,
    max_size_for_risk,
)
from .toolspec import TOOL_NAMES, TOOL_SPECS, coverage_summary, coverage_table
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
from .transport import (
    AdapterFixtureTransport,
    FixtureTransport,
    JsonTransport,
    UrllibAdapterTransport,
    UrllibReadTransport,
)
from .venue import AftermathVenue

__all__ = [
    "AccountCap",
    "AccountCapId",
    "AccountCapability",
    "AccountNumber",
    "AccountRef",
    "AccountSnapshot",
    "AdapterFixtureTransport",
    "AftermathAdapter",
    "AftermathVenue",
    "AmbiguousMarket",
    "B9",
    "BotState",
    "CANDLE_STREAM_PATH",
    "Candle",
    "CapabilityUnavailable",
    "CircuitBreaker",
    "CircuitBreakerTripped",
    "ConfigError",
    "ContractDriftError",
    "ContractError",
    "DEFAULT_API_BASE_URL",
    "DEFAULT_COLLATERAL_COIN_TYPE",
    "ExecutionClient",
    "FixtureTransport",
    "FundingPoint",
    "GAS_MODES",
    "GasCheck",
    "GasConfig",
    "HardLimits",
    "InspectedTx",
    "InspectionFailed",
    "JsonTransport",
    "KillSwitch",
    "Market",
    "MarketCatalog",
    "MarketId",
    "MarketRegistry",
    "MarketSpec",
    "MarketUnavailable",
    "MockAftermathAdapter",
    "NativeAccountId",
    "NativeCodec",
    "NormalizationError",
    "OpenOrder",
    "OrderToPlace",
    "PositionSnapshot",
    "PreviewError",
    "PreviewOk",
    "PreviewRejected",
    "PriceSnapshot",
    "PtbPipeline",
    "RuntimeConfig",
    "SerialGate",
    "ShutdownHandler",
    "SnapshotStreamState",
    "SoftLimits",
    "SuiAddress",
    "TOOL_NAMES",
    "TOOL_SPECS",
    "TxIntent",
    "UrllibAdapterTransport",
    "UrllibReadTransport",
    "WriteDenied",
    "api_base_url",
    "assert_not_retired_host",
    "assert_runtime_enablement",
    "assess_margin_health",
    "check_gas_mode",
    "coverage_summary",
    "coverage_table",
    "encode_bigints",
    "from_bigint_wire",
    "inspect",
    "market_candles_subscription",
    "max_size_for_risk",
    "normalise_instrument",
    "parse_gas_mode",
    "parse_preview",
    "reconcile",
    "sign_inspected",
    "to_bigint_wire",
]
