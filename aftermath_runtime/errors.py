"""Fail-closed errors for the Aftermath venue overlay."""


class AftermathRuntimeError(RuntimeError):
    """Base error for the read-only runtime."""


class ContractError(AftermathRuntimeError):
    """The API response does not match the pinned/expected contract."""


class NormalizationError(ContractError):
    """A response value cannot be normalized without guessing."""


class ContractDriftError(NormalizationError):
    """Machine-readable response-shape divergence from the pinned contract."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        field: str,
        observed_shape: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.observed_shape = observed_shape

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field": self.field,
            "observedShape": self.observed_shape,
        }


class MarketUnavailable(AftermathRuntimeError):
    """A market or required market capability is unavailable."""


class AmbiguousMarket(MarketUnavailable):
    """More than one market matches the requested symbol."""


class WriteDenied(AftermathRuntimeError):
    """A caller attempted to cross the read-only runtime boundary."""
