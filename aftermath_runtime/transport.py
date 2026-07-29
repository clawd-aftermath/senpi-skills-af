"""Transport injection for no-network tests and allowlisted read-only HTTP."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol
from urllib.request import Request, urlopen

from .errors import ContractError, WriteDenied


class JsonTransport(Protocol):
    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        """POST JSON to an allowlisted read endpoint."""


READ_PATHS = frozenset(
    {
        "/api/perpetuals/markets",
        "/api/perpetuals/markets/prices",
        "/api/perpetuals/market/candle-history",
        "/api/perpetuals/market/funding-history",
        "/api/perpetuals/accounts",
        "/api/perpetuals/accounts/owned",
        "/api/perpetuals/accounts/positions",
        "/api/ccxt/myPendingOrders",
    }
)


@dataclass
class FixtureTransport:
    """Deterministic in-memory transport keyed by API path."""

    responses: Mapping[str, Any]
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        if path not in READ_PATHS:
            raise WriteDenied(f"read-only transport denied {path}")
        self.calls.append((path, dict(payload)))
        if path not in self.responses:
            raise ContractError(f"no fixture response for {path}")
        response = self.responses[path]
        return response(path, payload) if callable(response) else response


@dataclass(frozen=True)
class UrllibReadTransport:
    """Opt-in live read transport; writes are structurally impossible.

    Construction requires two independent acknowledgements so importing this
    module or selecting a default transport can never open the network.
    """

    base_url: str = "https://v2-preview.aftermath.finance"
    timeout_seconds: float = 15.0
    allow_network: bool = False

    def __post_init__(self) -> None:
        if self.allow_network is not True:
            raise WriteDenied("live reads require allow_network=True")
        if os.environ.get("AFTERMATH_ALLOW_LIVE_READS") != "1":
            raise WriteDenied(
                "live reads require AFTERMATH_ALLOW_LIVE_READS=1"
            )
        if self.timeout_seconds <= 0:
            raise ContractError("timeout_seconds must be positive")

    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        if path not in READ_PATHS:
            raise WriteDenied(f"read-only transport denied {path}")
        body = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        request = Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
            raw = response.read()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ContractError(f"{path} returned non-JSON content") from exc
