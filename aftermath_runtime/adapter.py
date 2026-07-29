"""THE adapter.  One module; every strategy runs through it.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

The v1 trick, restated for V2: do not port 99 strategies, put ONE adapter
underneath them.  ``AftermathAdapter.call_tool(name, arguments)`` presents the
upstream MCP tool surface that strategy scanners already call, and implements it
entirely against Aftermath V2.  Because the interface matches what the packages
invoke, every package runs without being individually rewritten.

Three consequences follow, and they are the point of the design:

1. **No strategy file talks to the API.**  The adapter is the only seam.
2. **The best practices live here** — preview gating, transaction inspection,
   ID typing, BigInt wire format, circuit breakers, the kill switch, refresh
   after mutation, serialised deposits.  Putting them in the adapter is what
   makes them apply to all strategies at once and impossible to bypass.
3. **Hyperliquid is gone, not proxied.**  Upstream call *signatures* are kept
   so strategies need no rewrite; underneath, the venue's semantics are
   replaced, not re-pointed:

   ============================  ==========================================
   upstream (Hyperliquid)        Aftermath
   ============================  ==========================================
   ``marginPct`` of withdrawable explicit collateral allocation, in units
   leverage-as-sizing            leverage as a market risk parameter
   ``xyz:`` HIP-3 prefixes       stripped; markets are API-issued object ids
   dex-local asset-id math       no asset ids at all; resolve, never construct
   cross-margin account value    isolated margin, per position
   ``sendAsset``/``destinationDex`` no analogue; not proxied
   ============================  ==========================================

Reads never raise for an empty market universe: **no markets are live on
Aftermath yet and zero markets is expected.**  Resolving a specific instrument
against an empty universe does raise, because the alternative is inventing one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .accounts import (
    AccountCapability,
    OWNED_ACCOUNTS_PATH,
    owned_accounts_request,
    parse_owned_accounts,
    select_account,
)
from .config import RuntimeConfig
from .errors import (
    CapabilityUnavailable,
    ConfigError,
    ContractError,
    MarketUnavailable,
    NormalizationError,
    WriteDenied,
)
from .execution import (
    AccountRef,
    ExecutionClient,
    MAX_ORDER_SIZE_PATH,
    max_order_size_request,
)
from .gas import GAS_POOL_PATH, GasConfig, gas_pool_request, sponsor_from_pool
from .ids import (
    AccountNumber,
    MarketId,
    NativeAccountId,
    SuiAddress,
    normalise_instrument,
)
from .markets import ALL_MARKETS_PATH, Market, MarketCatalog, all_markets_request
from .safety import (
    BotState,
    CircuitBreaker,
    KillSwitch,
    SerialGate,
    assess_margin_health,
)
from .stream import CANDLE_RESOLUTIONS
from .toolspec import (
    BUILD_ONLY,
    TOOL_NAMES,
    TOOLS_BY_NAME,
    UNAVAILABLE,
)

PRICES_PATH = "/api/perpetuals/markets/prices"
STATS_PATH = "/api/perpetuals/markets/24hr-stats"
ORDERBOOKS_PATH = "/api/perpetuals/markets/orderbooks"
CANDLES_PATH = "/api/perpetuals/market/candle-history"
FUNDING_PATH = "/api/perpetuals/market/funding-history"
POSITIONS_PATH = "/api/perpetuals/accounts/positions"
PENDING_ORDERS_PATH = "/api/ccxt/myPendingOrders"
ORDER_HISTORY_PATH = "/api/perpetuals/account/order-history"
ORDER_HISTORY_DETAILED_PATH = "/api/perpetuals/account/order-history-detailed"
COLLATERAL_HISTORY_PATH = "/api/perpetuals/account/collateral-history"
MARGIN_HISTORY_PATH = "/api/perpetuals/account/margin-history"

# Upstream candle interval spellings -> the v3.0.0 `resolution` enum.  v3.0.0
# removed `intervalMs`/`interval_ms` entirely; nothing here emits either.
_RESOLUTION_ALIASES = {
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
    "30min": "30m",
    "60m": "1h",
    "1hour": "1h",
    "4hour": "4h",
    "1day": "1d",
    "d": "1d",
    "w": "1w",
    "1week": "1w",
    "1month": "1mo",
    "1M": "1mo",
}


def _resolution(value: str) -> str:
    text = str(value).strip()
    resolved = _RESOLUTION_ALIASES.get(text, _RESOLUTION_ALIASES.get(text.lower(), text.lower()))
    if resolved not in CANDLE_RESOLUTIONS:
        raise NormalizationError(
            f"unsupported candle resolution {value!r}; Aftermath v3 resolutions "
            f"are {sorted(CANDLE_RESOLUTIONS)}"
        )
    return resolved


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value[:-1] if value.endswith("n") else value
        try:
            return float(text)
        except ValueError:
            return default
    return default


@dataclass
class AdapterState:
    """Cached venue state with EXPLICIT invalidation.

    State goes stale the instant anything is mutated, so every build path calls
    ``invalidate()``.  Nothing here has a time-based TTL that could quietly
    serve a post-fill decision from a pre-fill snapshot.
    """

    catalog: MarketCatalog | None = None
    account: AccountCapability | None = None
    positions: Mapping[str, Any] | None = None

    def invalidate(self) -> None:
        self.positions = None
        self.account = None


class AftermathAdapter:
    """The Senpi MCP tool surface, served by Aftermath V2.

    ``transport`` is injected: pass an ``AdapterFixtureTransport`` for offline
    runs and tests, ``UrllibAdapterTransport`` for live reads.  The adapter
    itself opens no sockets and reads no credentials.
    """

    def __init__(
        self,
        transport: Any,
        config: RuntimeConfig,
        *,
        gas: GasConfig | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        clock: Callable[[], float] = time.time,
        log: Callable[[str], None] = lambda message: None,
    ) -> None:
        self._transport = transport
        self._config = config
        self._gas = gas or GasConfig(
            mode=config.gas_mode,
            budget_mist=config.gas_budget_mist,
            gas_coin_type=config.gas_coin_type,
        )
        self._clock = clock
        self._log = log
        self._state = AdapterState()
        self._deposit_gate = SerialGate()
        self.circuit_breaker = circuit_breaker or CircuitBreaker(log=log)
        self.execution = ExecutionClient(
            transport, gas=self._gas, armed=config.armed
        )
        self.kill_switch = KillSwitch(
            max_silence_seconds=120.0,
            cancel_all=self._cancel_all_and_verify,
            log=log,
        )

    # ── Introspection ────────────────────────────────────────────

    @property
    def tool_names(self) -> tuple[str, ...]:
        return TOOL_NAMES

    @property
    def config(self) -> RuntimeConfig:
        return self._config

    @property
    def gas(self) -> GasConfig:
        return self._gas

    # ── The single entry point every strategy uses ───────────────

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> Any:
        """Serve an upstream MCP tool call from Aftermath V2.

        An unknown tool name raises rather than returning an empty payload: a
        strategy silently receiving ``{}`` from a typo is exactly the class of
        bug that ships to production and no-trades forever.
        """
        args = dict(arguments or {})
        spec = TOOLS_BY_NAME.get(name)
        if spec is None:
            raise CapabilityUnavailable(
                name,
                "unknown tool. The adapter implements exactly the upstream "
                f"surface: {', '.join(TOOL_NAMES)}",
            )
        if spec.status == UNAVAILABLE:
            raise CapabilityUnavailable(name, spec.note or spec.backing)
        if spec.status == BUILD_ONLY:
            # Order matters: refuse a disarmed runtime BEFORE touching the
            # network, so an accidentally-enabled strategy makes no requests at
            # all, and check the breaker before resolving gas.
            if not self._config.armed:
                raise WriteDenied(
                    f"refusing to build {name}: the runtime is not armed. "
                    "Arming is a single explicit flag (AF_ARMED=1) and every "
                    "strategy in this repository ships disabled."
                )
            self.circuit_breaker.assert_can_trade()
            self.ensure_gas_ready()
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:  # pragma: no cover - guarded by the parity test
            raise CapabilityUnavailable(name, "no handler bound")
        return handler(args)

    # ── Gas ──────────────────────────────────────────────────────

    def ensure_gas_ready(self) -> GasConfig:
        """Resolve the sponsor before the first sponsored build.

        ``/api/gas-pool/pool`` is a POST that requires ``{walletAddress}``.  A
        pool that will not answer is a hard failure with an actionable remedy —
        the runtime never silently falls back to another gas mode, because an
        operator who chose ``sponsored`` may not hold any SUI at all.
        """
        if self._gas.mode != "sponsored" or self._gas.sponsor is not None:
            return self._gas
        wallet = self.require_wallet()
        try:
            payload = self._transport.post(GAS_POOL_PATH, gas_pool_request(wallet))
        except Exception as exc:  # noqa: BLE001
            raise ConfigError(
                f"sponsored gas selected but the gas pool is unreachable: {exc}. "
                "Set AF_GAS_MODE=self and fund the wallet with SUI, or retry "
                "when the pool is up."
            ) from exc
        sponsor = sponsor_from_pool(payload if isinstance(payload, Mapping) else {})
        if sponsor is None:
            raise ConfigError(
                "the gas pool returned no sponsor address; set AF_GAS_MODE=self "
                "or ask Aftermath to whitelist this wallet"
            )
        self._gas = GasConfig(
            mode=self._gas.mode,
            budget_mist=self._gas.budget_mist,
            sponsor=sponsor,
            gas_coin_type=self._gas.gas_coin_type,
        )
        self.execution = ExecutionClient(
            self._transport, gas=self._gas, armed=self._config.armed
        )
        return self._gas

    # ── Market universe ──────────────────────────────────────────

    def refresh_markets(self) -> MarketCatalog:
        payload = self._transport.post(
            ALL_MARKETS_PATH,
            all_markets_request(self._config.collateral_coin_type),
        )
        catalog = MarketCatalog.from_api(
            payload, collateral_coin_type=self._config.collateral_coin_type
        )
        if catalog.is_empty:
            self._log(
                "no Aftermath perpetual markets are live for collateral "
                f"{self._config.collateral_coin_type} — expected before the "
                "relaunch; strategies will find nothing to trade"
            )
        self._state.catalog = catalog
        return catalog

    @property
    def catalog(self) -> MarketCatalog:
        if self._state.catalog is None:
            return self.refresh_markets()
        return self._state.catalog

    def resolve_market(self, instrument: str) -> Market:
        return self.catalog.resolve(instrument)

    # ── Account resolution ───────────────────────────────────────

    def owned_accounts(self) -> tuple[AccountCapability, ...]:
        wallet = self.require_wallet()
        payload = self._transport.post(
            OWNED_ACCOUNTS_PATH, owned_accounts_request(wallet)
        )
        return parse_owned_accounts(payload)

    def require_wallet(self) -> SuiAddress:
        if not self._config.wallet_address:
            raise ContractError(
                "no wallet configured: set AF_WALLET_ADDRESS to your Sui wallet "
                "address. That is the only secret this runtime needs, and it is "
                "an address, never a key."
            )
        return SuiAddress(self._config.wallet_address)

    def account(self) -> AccountCapability:
        if self._state.account is not None:
            return self._state.account
        caps = self.owned_accounts()
        chosen = select_account(
            caps,
            collateral_coin_type=self._config.collateral_coin_type,
            preferred_account_id=self._config.account_id,
        )
        if chosen is None:
            raise ContractError(
                "this wallet owns no Aftermath perpetuals account for "
                f"collateral {self._config.collateral_coin_type}. Run the "
                "composed onboarding PTB (create-account + deposit + allocate) "
                "to provision one."
            )
        self._state.account = chosen
        return chosen

    def account_ref(self) -> AccountRef:
        cap = self.account()
        return AccountRef(
            account_id=cap.account_id,
            wallet_address=self.require_wallet(),
            account_cap_id=cap.cap_object_id,
        )

    # ── Raw reads ────────────────────────────────────────────────

    def positions_payload(self, account_id: NativeAccountId) -> Mapping[str, Any]:
        payload = self._transport.post(
            POSITIONS_PATH, {"accountIds": [account_id.wire]}
        )
        if not isinstance(payload, Mapping):
            raise ContractError(f"{POSITIONS_PATH} must answer an object")
        accounts = payload.get("accounts")
        if not isinstance(accounts, list):
            raise ContractError(f"{POSITIONS_PATH} 'accounts' must be an array")
        matches = [
            row
            for row in accounts
            if isinstance(row, Mapping)
            and NativeAccountId(row.get("accountId")) == account_id
        ]
        if len(matches) != 1:
            raise ContractError(
                f"expected exactly one account {account_id.value}, found "
                f"{len(matches)}"
            )
        self._state.positions = matches[0]
        return matches[0]

    def prices(self, markets: Sequence[Market]) -> dict[str, Mapping[str, Any]]:
        if not markets:
            return {}
        payload = self._transport.post(
            PRICES_PATH, {"marketIds": [str(m.market_id) for m in markets]}
        )
        if not isinstance(payload, Mapping):
            raise ContractError(f"{PRICES_PATH} must answer an object")
        rows = payload.get("marketsPrices")
        if not isinstance(rows, list):
            raise ContractError(f"{PRICES_PATH} 'marketsPrices' must be an array")
        return {str(row.get("marketId")): row for row in rows if isinstance(row, Mapping)}

    def stats(self, markets: Sequence[Market]) -> list[Mapping[str, Any]]:
        if not markets:
            return []
        payload = self._transport.post(
            STATS_PATH, {"marketIds": [str(m.market_id) for m in markets]}
        )
        if not isinstance(payload, Mapping):
            raise ContractError(f"{STATS_PATH} must answer an object")
        rows = payload.get("marketsStats")
        return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []

    def candles(
        self,
        market: Market,
        resolution: str,
        from_timestamp_ms: int,
        to_timestamp_ms: int,
    ) -> list[Mapping[str, Any]]:
        payload = self._transport.post(
            CANDLES_PATH,
            {
                "marketId": str(market.market_id),
                "resolution": _resolution(resolution),
                "fromTimestamp": int(from_timestamp_ms),
                "toTimestamp": int(to_timestamp_ms),
            },
        )
        if not isinstance(payload, Mapping):
            raise ContractError(f"{CANDLES_PATH} must answer an object")
        rows = payload.get("candles")
        return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []

    def funding_history(
        self,
        market: Market,
        from_timestamp_ms: int,
        to_timestamp_ms: int,
        limit: int | None = None,
    ) -> list[Mapping[str, Any]]:
        body: dict[str, Any] = {
            "marketId": str(market.market_id),
            "fromTimestamp": int(from_timestamp_ms),
            "toTimestamp": int(to_timestamp_ms),
        }
        if limit is not None:
            body["limit"] = int(limit)
        payload = self._transport.post(FUNDING_PATH, body)
        if not isinstance(payload, Mapping):
            raise ContractError(f"{FUNDING_PATH} must answer an object")
        rows = payload.get("history")
        return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []

    def pending_orders(
        self, account_number: AccountNumber, market: Market
    ) -> list[Mapping[str, Any]]:
        """CCXT READ path: ``accountNumber`` (a number) and ``chId``.

        The CCXT *write* surface uses the capability object id under the same
        ``accountId`` name.  They are not interchangeable.
        """
        payload = self._transport.post(
            PENDING_ORDERS_PATH,
            {"accountNumber": account_number.value, "chId": str(market.market_id)},
        )
        if isinstance(payload, Mapping) and payload.get("error"):
            raise ContractError(f"{PENDING_ORDERS_PATH}: {payload['error']}")
        if not isinstance(payload, list):
            raise ContractError(f"{PENDING_ORDERS_PATH} must answer an array")
        return [row for row in payload if isinstance(row, Mapping)]

    def all_pending_orders(self) -> list[Mapping[str, Any]]:
        account_number = AccountNumber(self.account().account_id.as_number())
        orders: list[Mapping[str, Any]] = []
        for market in self.catalog.markets:
            orders.extend(self.pending_orders(account_number, market))
        return orders

    # ── Kill-switch cancellation, VERIFIED ───────────────────────

    def _cancel_all_and_verify(self) -> list[Mapping[str, Any]]:
        """Cancel every resting order, then RE-READ to prove it.

        Returns the survivors.  A non-empty return makes the kill switch report
        failure instead of a comfortable lie.
        """
        try:
            resting = self.all_pending_orders()
        except Exception as exc:  # noqa: BLE001 - unknown exposure is exposure
            self._log(f"cancel-all: could not read pending orders: {exc}")
            return [{"unknown": True, "reason": str(exc)}]
        if not resting:
            return []
        if not self._config.armed:
            self._log(
                "cancel-all: the runtime is not armed, so no cancellation "
                f"transaction can be built; {len(resting)} order(s) remain"
            )
            return list(resting)
        # The kill switch does not go through call_tool, so gas must be
        # resolved here too — a cancel-all that cannot pay for itself is not a
        # kill switch.
        self.ensure_gas_ready()
        market_ids_to_data: dict[str, Any] = {}
        for order in resting:
            symbol = str(order.get("symbol", ""))
            market = self.catalog.try_resolve(symbol)
            if market is None:
                continue
            market_ids_to_data.setdefault(str(market.market_id), {"orderIds": []})
        self.execution.cancel_orders(
            self.account_ref(), market_ids_to_data, should_abort_on_missing_id=False
        )
        self._state.invalidate()
        # Re-read.  Cancellation is verified, never assumed.
        return list(self.all_pending_orders())

    # ── Tool handlers ────────────────────────────────────────────

    def _tool_market_list_instruments(self, args: Mapping[str, Any]) -> dict[str, Any]:
        catalog = self.refresh_markets()
        instruments = [
            {
                "symbol": market.symbol,
                "marketId": str(market.market_id),
                "collateralCoinType": market.collateral_coin_type,
                "maxLeverage": market.max_leverage,
                "lotSize": str(market.lot_size_native) + "n",
                "tickSize": str(market.tick_size_native) + "n",
                "minOrderUsdValue": market.min_order_usd_value,
                "makerFee": market.maker_fee,
                "takerFee": market.taker_fee,
                "priorityTakerFee": market.priority_taker_fee,
                "isDelisted": False,
            }
            for market in catalog.markets
        ]
        return {
            "success": True,
            "venue": "aftermath",
            "data": {"instruments": instruments, "count": len(instruments)},
            "warnings": (
                []
                if instruments
                else ["no Aftermath markets are live yet (expected pre-relaunch)"]
            ),
        }

    def _tool_market_get_prices(self, args: Mapping[str, Any]) -> dict[str, Any]:
        requested = args.get("assets") or args.get("markets") or []
        markets = (
            self.catalog.resolve_many(requested) if requested else self.catalog.markets
        )
        rows = self.prices(markets)
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                market.symbol: {
                    "markPrice": _num((rows.get(str(market.market_id)) or {}).get("markPrice")),
                    "indexPrice": _num((rows.get(str(market.market_id)) or {}).get("basePrice")),
                    "midPrice": _num((rows.get(str(market.market_id)) or {}).get("midPrice")),
                    "marketId": str(market.market_id),
                }
                for market in markets
            },
        }

    def _tool_market_get_asset_data(self, args: Mapping[str, Any]) -> dict[str, Any]:
        asset = args.get("asset") or args.get("coin") or args.get("symbol")
        if not asset:
            raise NormalizationError("market_get_asset_data requires an asset")
        # A HIP-3 `dex` argument is accepted and DISCARDED: it addresses a
        # Hyperliquid builder dex that does not exist here.
        market = self.resolve_market(str(asset))
        price_rows = self.prices([market])
        price = price_rows.get(str(market.market_id), {})
        stats_rows = self.stats([market])
        stats = stats_rows[0] if stats_rows else {}

        data: dict[str, Any] = {
            "marketId": str(market.market_id),
            "symbol": market.symbol,
            "asset_context": {
                # Aftermath reports open interest in base tokens on marketState.
                "openInterest": market.open_interest,
                "markPx": _num(price.get("markPrice"), market.index_price),
                "oraclePx": _num(price.get("basePrice"), market.index_price),
                "midPx": _num(price.get("midPrice")),
                "dayNtlVlm": _num(stats.get("volumeUsd")),
                "prevDayPx": None,
                "priceChangePercentage": _num(stats.get("priceChangePercentage")),
                "maxLeverage": market.max_leverage,
                "funding": market.estimated_funding_rate,
                "nextFundingTimestampMs": market.next_funding_timestamp_ms,
            },
            "market_params": {
                "marginRatioInitial": market.margin_ratio_initial,
                "marginRatioMaintenance": market.margin_ratio_maintenance,
                "minOrderUsdValue": market.min_order_usd_value,
                "makerFee": market.maker_fee,
                "takerFee": market.taker_fee,
            },
        }

        intervals = args.get("candle_intervals") or args.get("intervals") or []
        if intervals:
            now_ms = int(self._clock() * 1000)
            candles: dict[str, list[dict[str, Any]]] = {}
            for interval in intervals:
                resolution = _resolution(interval)
                lookback = args.get("candle_lookback_ms") or 200 * _interval_ms(resolution)
                rows = self.candles(
                    market, resolution, now_ms - int(lookback), now_ms
                )
                candles[str(interval)] = [
                    {
                        "t": row.get("timestamp"),
                        "o": str(_num(row.get("open"))),
                        "h": str(_num(row.get("high"))),
                        "l": str(_num(row.get("low"))),
                        "c": str(_num(row.get("close"))),
                        "v": str(_num(row.get("volume"))),
                    }
                    for row in rows
                ]
            data["candles"] = candles

        if args.get("include_funding"):
            now_ms = int(self._clock() * 1000)
            data["funding_history"] = self.funding_history(
                market, now_ms - 7 * 86_400_000, now_ms, limit=200
            )

        if args.get("include_order_book"):
            payload = self._transport.post(
                ORDERBOOKS_PATH, {"marketIds": [str(market.market_id)]}
            )
            books = payload.get("orderbooks") if isinstance(payload, Mapping) else None
            data["order_book"] = books[0] if isinstance(books, list) and books else None

        # oi_velocity has no Aftermath source. Omitting it is deliberate: the
        # upstream scanners already fall back to their own OI baseline.
        return {"success": True, "venue": "aftermath", "data": data}

    def _tool_market_get_funding_history(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        market = self.resolve_market(str(args.get("asset") or args.get("coin") or ""))
        now_ms = int(self._clock() * 1000)
        start = int(args.get("from_timestamp_ms") or now_ms - 7 * 86_400_000)
        end = int(args.get("to_timestamp_ms") or now_ms)
        rows = self.funding_history(market, start, end, args.get("limit"))
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                "marketId": str(market.market_id),
                "symbol": market.symbol,
                "fundingIntervalMs": market.funding_frequency_ms,
                "history": rows,
            },
        }

    def _tool_market_get_funding_regime(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        requested = args.get("assets") or args.get("universe") or []
        markets = (
            self.catalog.resolve_many(requested) if requested else self.catalog.markets
        )
        regimes = {}
        for market in markets:
            rate = market.estimated_funding_rate
            # Annualised from the market's own funding frequency; no constant is
            # assumed about how often funding settles.
            periods_per_year = (
                (365 * 86_400_000) / market.funding_frequency_ms
                if market.funding_frequency_ms
                else 0.0
            )
            annualised = rate * periods_per_year * 100.0
            if annualised > 30:
                regime = "crowded_long"
            elif annualised < -30:
                regime = "crowded_short"
            elif abs(annualised) < 5:
                regime = "neutral"
            else:
                regime = "tilted_long" if annualised > 0 else "tilted_short"
            regimes[market.symbol] = {
                "marketId": str(market.market_id),
                "fundingRate": rate,
                "fundingAnnualizedPct": annualised,
                "fundingIntervalMs": market.funding_frequency_ms,
                "regime": regime,
            }
        return {"success": True, "venue": "aftermath", "data": regimes}

    def _tool_strategy_get_clearinghouse_state(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Isolated-margin state in the upstream envelope shape.

        The upstream payload has ``main`` and ``xyz`` sections because
        Hyperliquid exposes two views of one CROSS-margined wallet.  Aftermath
        has neither a builder dex nor cross margin, so only ``main`` is emitted.
        Callers that ``max()`` across the two sections keep working unchanged.

        ``totalMarginUsed`` is the sum of per-position ISOLATED collateral and
        ``totalNtlPos`` the sum of ABSOLUTE position notional.  Both policies
        are stated here rather than left implicit, because relabelling isolated
        collateral as a cross-margin aggregate is how a port silently mis-sizes.
        """
        cap = self.account()
        account = self.positions_payload(cap.account_id)
        positions = account.get("positions")
        positions = positions if isinstance(positions, list) else []

        asset_positions = []
        total_margin_used = 0.0
        total_notional = 0.0
        for row in positions:
            if not isinstance(row, Mapping):
                continue
            market = self.catalog.try_resolve(str(row.get("marketId", "")))
            size = _num(row.get("baseAssetAmount"))
            collateral_usd = _num(row.get("collateralUsd"))
            notional = abs(_num(row.get("quoteAssetNotionalAmount")))
            total_margin_used += collateral_usd
            total_notional += notional
            asset_positions.append(
                {
                    "position": {
                        # `coin` keeps the upstream key so scanners parse it, but
                        # its VALUE is an Aftermath symbol with no dex prefix.
                        "coin": market.symbol if market else str(row.get("marketId", "")),
                        "marketId": str(row.get("marketId", "")),
                        "szi": str(size),
                        "marginUsed": str(collateral_usd),
                        "entryPx": str(_num(row.get("entryPrice"))),
                        "liquidationPx": str(_num(row.get("liquidationPrice"))),
                        "leverage": {
                            "type": "isolated",
                            "value": _num(row.get("leverage")),
                        },
                        "unrealizedPnl": str(_num(row.get("unrealizedPnlUsd"))),
                        "marginRatio": _num(row.get("marginRatio")),
                        "marginHealth": (
                            assess_margin_health(
                                _num(row.get("marginRatio")),
                                market.margin_ratio_maintenance,
                            ).zone
                            if market and _num(row.get("marginRatio")) > 0
                            else None
                        ),
                    }
                }
            )

        section = {
            "marginSummary": {
                "accountValue": str(_num(account.get("totalEquityUsd"))),
                "totalMarginUsed": str(total_margin_used),
                "totalNtlPos": str(total_notional),
                "totalRawUsd": str(_num(account.get("totalEquityUsd"))),
            },
            "withdrawable": str(_num(account.get("availableCollateralUsd"))),
            "assetPositions": asset_positions,
        }
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                "main": section,
                "accountId": cap.account_id.wire,
                "marginModel": "isolated",
                "notes": [
                    "Aftermath uses ISOLATED margin: unallocated collateral "
                    "protects nothing.",
                    "There is no builder-dex section; 'main' is the whole "
                    "account.",
                ],
            },
        }

    def _tool_strategy_get_open_orders(self, args: Mapping[str, Any]) -> dict[str, Any]:
        asset = args.get("asset") or args.get("coin")
        account_number = AccountNumber(self.account().account_id.as_number())
        if asset:
            markets = [self.resolve_market(str(asset))]
        else:
            markets = list(self.catalog.markets)
        orders: list[Mapping[str, Any]] = []
        for market in markets:
            orders.extend(self.pending_orders(account_number, market))
        return {
            "success": True,
            "venue": "aftermath",
            "data": {"orders": orders, "count": len(orders)},
        }

    def _tool_strategy_get_asset_trading_limits(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        market = self.resolve_market(str(args.get("asset") or args.get("coin") or ""))
        limits: dict[str, Any] = {
            "marketId": str(market.market_id),
            "symbol": market.symbol,
            "maxLeverage": market.max_leverage,
            "minOrderUsdValue": market.min_order_usd_value,
            "lotSize": f"{market.lot_size_native}n",
            "tickSize": f"{market.tick_size_native}n",
            "maxPendingOrders": market.max_pending_orders,
            "marginRatioInitial": market.margin_ratio_initial,
            "marginRatioMaintenance": market.margin_ratio_maintenance,
        }
        side = args.get("side")
        if side is not None:
            try:
                limits["maxOrderSize"] = self._transport.post(
                    MAX_ORDER_SIZE_PATH,
                    max_order_size_request(
                        self.account().account_id,
                        market.market_id,
                        side=side,
                        price=args.get("price"),
                        leverage=args.get("leverage"),
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - advisory, must not block
                limits["maxOrderSizeError"] = str(exc)
        return {"success": True, "venue": "aftermath", "data": limits}

    def _tool_audit_query(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """Paginated order history.

        Uses ``beforeTimestampCursor`` / ``nextBeforeTimestampCursor`` exactly
        as the error-handling skill specifies, and stops on a repeated cursor so
        a server that echoes the cursor cannot spin forever.
        """
        cap = self.account()
        limit = int(args.get("limit") or 100)
        pages = int(args.get("pages") or 1)
        cursor = args.get("beforeTimestampCursor")
        rows: list[Any] = []
        seen: set[Any] = set()
        for _ in range(max(1, pages)):
            body: dict[str, Any] = {
                "accountId": cap.account_id.wire,
                "limit": limit,
            }
            if cursor is not None:
                body["beforeTimestampCursor"] = int(cursor)
            if args.get("eventTypes"):
                body["eventTypes"] = list(args["eventTypes"])
            payload = self._transport.post(ORDER_HISTORY_PATH, body)
            if not isinstance(payload, Mapping):
                raise ContractError(f"{ORDER_HISTORY_PATH} must answer an object")
            page = payload.get("orders")
            if isinstance(page, list):
                rows.extend(page)
            cursor = payload.get("nextBeforeTimestampCursor")
            if cursor is None or cursor in seen:
                break
            seen.add(cursor)
        return {
            "success": True,
            "venue": "aftermath",
            "data": {"events": rows, "count": len(rows), "nextCursor": cursor},
        }

    def _tool_execution_get_closed_position_details(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        cap = self.account()
        body: dict[str, Any] = {"accountId": cap.account_id.wire}
        if args.get("limit"):
            body["limit"] = int(args["limit"])
        payload = self._transport.post(ORDER_HISTORY_DETAILED_PATH, body)
        return {"success": True, "venue": "aftermath", "data": payload}

    def _tool_strategy_get_pnl_and_account_value_history(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        cap = self.account()
        body = {"accountId": cap.account_id.wire}
        collateral = self._transport.post(COLLATERAL_HISTORY_PATH, dict(body))
        margin = self._transport.post(MARGIN_HISTORY_PATH, dict(body))
        return {
            "success": True,
            "venue": "aftermath",
            "data": {"collateralHistory": collateral, "marginHistory": margin},
        }

    def _tool_account_get_portfolio(self, args: Mapping[str, Any]) -> dict[str, Any]:
        caps = self.owned_accounts()
        accounts = []
        for cap in caps:
            try:
                payload = self.positions_payload(cap.account_id)
            except ContractError as exc:
                accounts.append(
                    {"accountId": cap.account_id.wire, "error": str(exc)}
                )
                continue
            accounts.append(
                {
                    "accountId": cap.account_id.wire,
                    "accountCapId": str(cap.cap_object_id),
                    "collateralCoinType": cap.collateral_coin_type,
                    "totalEquityUsd": _num(payload.get("totalEquityUsd")),
                    "availableCollateralUsd": _num(
                        payload.get("availableCollateralUsd")
                    ),
                    "unrealizedPnlUsd": _num(payload.get("totalUnrealizedPnlUsd")),
                    "positionCount": len(payload.get("positions") or []),
                }
            )
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                "accounts": accounts,
                "walletBalances": None,
                "gaps": [
                    "wallet-level idle balances unavailable: the /api/wallet/* "
                    "family is published in the spec but returns 404 on the "
                    "live host (verified 2026-07-28)"
                ],
            },
        }

    def _tool_strategy_list(self, args: Mapping[str, Any]) -> dict[str, Any]:
        caps = self.owned_accounts()
        return {
            "success": True,
            "venue": "aftermath",
            "data": {
                "strategies": [
                    {
                        "accountId": cap.account_id.wire,
                        "accountCapId": str(cap.cap_object_id),
                        "collateralCoinType": cap.collateral_coin_type,
                        "collateral": cap.collateral,
                        "isAgent": cap.is_agent,
                    }
                    for cap in caps
                ],
                "note": "Aftermath has accounts, not named strategies; Senpi "
                "strategy metadata lives in the Senpi control plane.",
            },
        }

    def _tool_strategy_get(self, args: Mapping[str, Any]) -> dict[str, Any]:
        return self._tool_strategy_get_clearinghouse_state(args)

    def _tool_user_get_referral_rewards(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        raise CapabilityUnavailable(
            "user_get_referral_rewards",
            "Aftermath referrals need a signed challenge (bytes + signature) "
            "which this runtime never produces; supply one out of band.",
        )

    def _tool_user_get_senpi_points(self, args: Mapping[str, Any]) -> dict[str, Any]:
        # v3.0.0: /api/rewards/points now REQUIRES bytes + signature, and the
        # response is {totalPoints} (float), not {points} (int).
        bytes_ = args.get("bytes")
        signature = args.get("signature")
        if not bytes_ or not signature:
            raise CapabilityUnavailable(
                "user_get_senpi_points",
                "/api/rewards/points requires a signed challenge (bytes + "
                "signature) as of v3.0.0; this runtime never signs, so the "
                "caller must supply one.",
            )
        payload = self._transport.post(
            "/api/rewards/points",
            {
                "walletAddress": str(self.require_wallet()),
                "bytes": bytes_,
                "signature": signature,
            },
        )
        total = payload.get("totalPoints") if isinstance(payload, Mapping) else None
        return {
            "success": True,
            "venue": "aftermath",
            "data": {"totalPoints": total},
        }

    # ── Mutations (build-only) ───────────────────────────────────

    def _tool_strategy_create_custom_strategy(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Composed onboarding: create-account + deposit + allocate, ONE PTB."""
        wallet = self.require_wallet()
        deposit = int(args.get("deposit_amount") or args.get("budget") or 0)
        allocations = [
            (self.resolve_market(str(symbol)).market_id, int(amount))
            for symbol, amount in (args.get("allocations") or {}).items()
        ]
        tx = self.execution.build_onboarding_ptb(
            wallet,
            collateral_coin_type=self._config.collateral_coin_type,
            deposit_amount=deposit,
            allocations=allocations,
        )
        self._state.invalidate()
        return _tx_result(tx)

    def _tool_strategy_create(self, args: Mapping[str, Any]) -> dict[str, Any]:
        tx = self.execution.create_account(
            self.require_wallet(),
            collateral_coin_type=self._config.collateral_coin_type,
        )
        self._state.invalidate()
        return _tx_result(tx)

    def _tool_strategy_top_up(self, args: Mapping[str, Any]) -> dict[str, Any]:
        amount = int(args.get("amount") or 0)
        with self._deposit_gate:
            tx = self.execution.deposit_collateral(
                self.account_ref(),
                collateral_coin_type=self._config.collateral_coin_type,
                deposit_amount=amount,
            )
        self._state.invalidate()
        return _tx_result(tx)

    def _tool_strategy_withdraw_funds(self, args: Mapping[str, Any]) -> dict[str, Any]:
        with self._deposit_gate:
            tx = self.execution.withdraw_collateral(
                self.account_ref(), withdraw_amount=int(args.get("amount") or 0)
            )
        self._state.invalidate()
        return _tx_result(tx)

    def _tool_strategy_update(self, args: Mapping[str, Any]) -> dict[str, Any]:
        market = self.resolve_market(str(args.get("asset") or args.get("coin") or ""))
        tx = self.execution.set_leverage(
            self.account_ref(),
            market.market_id,
            leverage=float(args.get("leverage") or 0),
        )
        self._state.invalidate()
        return _tx_result(tx)

    def _tool_strategy_pause(self, args: Mapping[str, Any]) -> dict[str, Any]:
        market_ids_to_data = {
            str(market.market_id): {"orderIds": []} for market in self.catalog.markets
        }
        tx = self.execution.cancel_orders(
            self.account_ref(), market_ids_to_data, should_abort_on_missing_id=False
        )
        self._state.invalidate()
        return _tx_result(tx)

    def _tool_strategy_open(self, args: Mapping[str, Any]) -> dict[str, Any]:
        return self._place(args, reduce_only=False)

    def _tool_strategy_close_positions(
        self, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._place(args, reduce_only=True)

    def _tool_strategy_close(self, args: Mapping[str, Any]) -> dict[str, Any]:
        raise WriteDenied(
            "strategy_close is a multi-transaction teardown (cancel -> "
            "reduce-only close -> withdraw) whose later steps depend on the "
            "realised fill. Drive the steps explicitly; a single call would "
            "have to guess the withdrawable amount."
        )

    def _place(self, args: Mapping[str, Any], *, reduce_only: bool) -> dict[str, Any]:
        market = self.resolve_market(str(args.get("asset") or args.get("coin") or ""))
        size = args.get("size_native") or args.get("size")
        if size is None:
            raise NormalizationError(
                "an explicit native size is required; Aftermath does not accept "
                "a percent-of-withdrawable margin fraction"
            )
        tx = self.execution.place_market_order(
            self.account_ref(),
            market.market_id,
            side=args.get("side", "buy"),
            size_native=int(size),
            collateral_change=float(args.get("collateral_change") or 0.0),
            slippage=float(args.get("slippage") or 0.01),
            reduce_only=reduce_only,
            has_position=bool(args.get("has_position", False)),
            leverage=args.get("leverage"),
        )
        self._state.invalidate()
        return _tx_result(tx)

    # ── Risk plumbing available to every strategy ────────────────

    def observe(self, state: BotState) -> list[str]:
        """Feed the circuit breakers and beat the kill switch."""
        self.kill_switch.heartbeat()
        return self.circuit_breaker.evaluate(state)


def _interval_ms(resolution: str) -> int:
    table = {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
        "12h": 43_200_000,
        "1d": 86_400_000,
        "3d": 259_200_000,
        "1w": 604_800_000,
        "1mo": 2_592_000_000,
    }
    return table[resolution]


def _tx_result(tx: Any) -> dict[str, Any]:
    """Report a built-and-inspected transaction WITHOUT implying it happened."""
    return {
        "success": True,
        "venue": "aftermath",
        "submitted": False,
        "data": {
            "txKind": tx.tx_kind,
            "intent": tx.intent.intent,
            "gasMode": tx.intent.gas.mode,
            "inspected": True,
            "deferred": dict(tx.deferred) if tx.deferred else None,
            "note": "built, previewed and inspected; NOT signed and NOT "
            "submitted. This runtime never broadcasts.",
        },
    }
