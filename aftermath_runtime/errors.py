"""Fail-closed errors for the Aftermath venue overlay."""


class AftermathRuntimeError(RuntimeError):
    """Base error for the read-only runtime."""


class ContractError(AftermathRuntimeError):
    """The API response does not match the pinned/expected contract."""


class NormalizationError(ContractError):
    """A response value cannot be normalized without guessing."""


class MarketUnavailable(AftermathRuntimeError):
    """A market or required market capability is unavailable."""


class AmbiguousMarket(MarketUnavailable):
    """More than one market matches the requested symbol."""


class WriteDenied(AftermathRuntimeError):
    """A caller attempted to cross the read-only runtime boundary."""
