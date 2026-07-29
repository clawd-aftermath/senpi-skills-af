"""Transport injection for no-network tests and allowlisted read-only HTTP."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol
from urllib.request import Request, urlopen

from .config import DEFAULT_API_BASE_URL, assert_not_retired_host
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

# Additional read routes the adapter needs.  Kept separate from READ_PATHS so
# the existing read-only transports keep their pinned, tested allowlist.
ADAPTER_READ_PATHS = frozenset(
    {
        "/api/perpetuals/all-markets",
        "/api/perpetuals/markets/24hr-stats",
        "/api/perpetuals/markets/orderbooks",
        "/api/perpetuals/market/order-history",
        "/api/perpetuals/account/order-history",
        "/api/perpetuals/account/order-history-detailed",
        "/api/perpetuals/account/collateral-history",
        "/api/perpetuals/account/margin-history",
        "/api/perpetuals/account/max-order-size",
        "/api/perpetuals/account/stop-order-datas",
        "/api/perpetuals/account/twap-order-datas",
        "/api/gas-pool/pool",
        "/api/rewards/points",
        "/api/rewards/expectedRewards",
        # Present in the spec, 404 live as of 2026-07-28.  Allowlisted so the
        # adapter can *try* and degrade gracefully, never so it can hard-fail.
        "/api/wallet/coin_balances",
        "/api/wallet/all_coin_balances",
    }
)

PREVIEW_PATHS = frozenset(
    {
        "/api/perpetuals/account/previews/place-market-order",
        "/api/perpetuals/account/previews/place-limit-order",
        "/api/perpetuals/account/previews/place-scale-order",
        "/api/perpetuals/account/previews/cancel-orders",
        "/api/perpetuals/account/previews/set-leverage",
        "/api/perpetuals/account/previews/edit-collateral",
    }
)

BUILD_PATHS = frozenset(
    {
        "/api/perpetuals/transactions/create-account",
        "/api/perpetuals/account/transactions/cancel-and-place-orders",
        "/api/perpetuals/account/transactions/place-scale-order",
        "/api/perpetuals/account/transactions/place-market-order",
        "/api/perpetuals/account/transactions/place-limit-order",
        "/api/perpetuals/account/transactions/cancel-orders",
        "/api/perpetuals/account/transactions/set-leverage",
        "/api/perpetuals/account/transactions/deposit-collateral",
        "/api/perpetuals/account/transactions/allocate-collateral",
        "/api/perpetuals/account/transactions/deallocate-collateral",
        "/api/perpetuals/account/transactions/withdraw-collateral",
        "/api/perpetuals/account/transactions/transfer-collateral",
        "/api/perpetuals/account/transactions/place-sl-tp-orders",
        "/api/perpetuals/account/transactions/place-stop-orders",
        "/api/perpetuals/account/transactions/edit-stop-orders",
        "/api/perpetuals/account/transactions/cancel-stop-orders",
        "/api/perpetuals/account/transactions/create-twap-orders",
        "/api/perpetuals/account/transactions/edit-twap-orders",
        "/api/perpetuals/account/transactions/cancel-twap-orders",
    }
)

# Deliberately absent from EVERY allowlist in this repository, so no transport
# can reach them: /api/ccxt/submit/*, /api/perpetuals/.../submit, and any other
# broadcast route.  Building and inspecting is in scope; submitting is not.
SUBMIT_PATHS_ARE_NEVER_ALLOWLISTED = True


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

    base_url: str = DEFAULT_API_BASE_URL
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
        assert_not_retired_host(self.base_url)

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


@dataclass
class AdapterFixtureTransport:
    """Offline transport for the adapter: reads, previews and BUILDS.

    Builds are allowed here because building is offline-safe in this
    repository: the fixture answers with a canned ``{txKind}``, nothing is
    signed, and no submit route exists in any allowlist.  Live building has its
    own class with a third opt-in.
    """

    responses: Mapping[str, Any]
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    allow_builds: bool = True

    @property
    def allowed(self) -> frozenset[str]:
        base = READ_PATHS | ADAPTER_READ_PATHS | PREVIEW_PATHS
        return base | BUILD_PATHS if self.allow_builds else base

    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        if path not in self.allowed:
            raise WriteDenied(f"transport denied {path}")
        self.calls.append((path, dict(payload)))
        if path not in self.responses:
            raise ContractError(f"no fixture response for {path}")
        response = self.responses[path]
        return response(path, payload) if callable(response) else response


@dataclass(frozen=True)
class UrllibAdapterTransport:
    """Opt-in live transport for the adapter.

    Reads and previews need the same two acknowledgements as
    ``UrllibReadTransport``.  Transaction BUILDING needs a third
    (``AFTERMATH_ALLOW_TX_BUILD=1``) because a build is the last step before a
    signature exists.  Submission is unreachable by construction: no submit
    route appears in any allowlist in this module.
    """

    base_url: str = DEFAULT_API_BASE_URL
    timeout_seconds: float = 15.0
    allow_network: bool = False
    allow_builds: bool = False

    def __post_init__(self) -> None:
        if self.allow_network is not True:
            raise WriteDenied("live calls require allow_network=True")
        if os.environ.get("AFTERMATH_ALLOW_LIVE_READS") != "1":
            raise WriteDenied("live calls require AFTERMATH_ALLOW_LIVE_READS=1")
        if self.allow_builds and os.environ.get("AFTERMATH_ALLOW_TX_BUILD") != "1":
            raise WriteDenied(
                "live transaction building requires AFTERMATH_ALLOW_TX_BUILD=1"
            )
        if self.timeout_seconds <= 0:
            raise ContractError("timeout_seconds must be positive")
        assert_not_retired_host(self.base_url)

    @property
    def allowed(self) -> frozenset[str]:
        base = READ_PATHS | ADAPTER_READ_PATHS | PREVIEW_PATHS
        return base | BUILD_PATHS if self.allow_builds else base

    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        if path not in self.allowed:
            raise WriteDenied(f"transport denied {path}")
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
