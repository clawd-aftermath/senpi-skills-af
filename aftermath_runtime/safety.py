"""Trading safety: margin health, sizing, circuit breakers, kill switch.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

Structure follows the vendored skill ``AFTERMATH_SKILLS_REF/skills/api/
safety-and-risk.md`` (v3.0.0).  Only its *patterns* are reused; its example
URLs name the retired v1 host and are never copied.

These live in the adapter layer on purpose.  Putting them here is what makes
them apply to every strategy at once and impossible for a strategy to forget.

Isolated margin is the model.  Wallet USDC -> deposit -> account *unallocated*
collateral -> explicit allocate -> per-position isolated margin.  Unallocated
collateral protects nothing.  Any code that assumes cross-margin is wrong.
"""

from __future__ import annotations

import signal
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .errors import CircuitBreakerTripped, NormalizationError

# ── Margin health ────────────────────────────────────────────────

SAFE = "SAFE"
WARNING = "WARNING"
DANGER = "DANGER"
LIQUIDATION = "LIQUIDATION"


@dataclass(frozen=True)
class MarginHealth:
    zone: str
    margin_ratio: float
    maintenance_ratio: float
    buffer_multiple: float


def assess_margin_health(margin_ratio: float, maintenance_ratio: float) -> MarginHealth:
    """Margin zone from the position's API-reported ratios.

    Zones per the skill: >2x safe, 1.5-2x warning, 1-1.5x danger, <1x
    liquidatable.  Both inputs come from the API; nothing is inferred from
    price.  Refuses to guess when data is missing — a fabricated "safe" is
    worse than an error.
    """
    for name, value in (
        ("marginRatio", margin_ratio),
        ("marginRatioMaintenance", maintenance_ratio),
    ):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise NormalizationError(f"{name} must be numeric")
        if value != value or value in (float("inf"), float("-inf")):
            raise NormalizationError(f"{name} must be finite")
    if maintenance_ratio <= 0:
        raise NormalizationError("marginRatioMaintenance must be positive")

    buffer = float(margin_ratio) / float(maintenance_ratio)
    if buffer < 1:
        zone = LIQUIDATION
    elif buffer < 1.5:
        zone = DANGER
    elif buffer < 2:
        zone = WARNING
    else:
        zone = SAFE
    return MarginHealth(zone, float(margin_ratio), float(maintenance_ratio), buffer)


# ── Position sizing ──────────────────────────────────────────────


def max_size_for_risk(
    account_collateral: float,
    entry_price: float,
    stop_loss_price: float,
    risk_percent: float = 2.0,
) -> float:
    """The 2% rule: risk at most ``risk_percent`` of collateral per trade.

    Sized off account collateral and the distance to the stop, exactly as the
    skill specifies.  Callers must still guard large orders with
    ``/api/perpetuals/account/max-order-size``.
    """
    if account_collateral <= 0:
        raise NormalizationError("account collateral must be positive")
    if not 0 < risk_percent <= 100:
        raise NormalizationError("risk_percent must be in (0, 100]")
    distance = abs(float(entry_price) - float(stop_loss_price))
    if distance <= 0:
        raise NormalizationError("entry and stop-loss prices must differ")
    return (float(account_collateral) * (risk_percent / 100.0)) / distance


def collateral_for_notional(notional_usd: float, leverage: float) -> float:
    """Isolated-margin collateral required for a target notional.

    Aftermath allocates COLLATERAL explicitly; there is no Hyperliquid-style
    ``marginPct`` of a shared cross-margin balance.  Upstream percent-of-
    withdrawable sizing is translated to an explicit collateral amount here so
    the venue-native concept is the only one that reaches the API.
    """
    if leverage <= 0:
        raise NormalizationError("leverage must be positive")
    if notional_usd <= 0:
        raise NormalizationError("notional must be positive")
    return float(notional_usd) / float(leverage)


# ── Two-tier circuit breakers ────────────────────────────────────


@dataclass(frozen=True)
class SoftLimits:
    """Tier 1 — advisory.  Exceeding these logs, it does not halt."""

    max_drawdown_pct: float = 5.0
    max_position_notional: float = 50_000.0
    max_leverage: float = 5.0
    min_margin_buffer: float = 2.0


@dataclass(frozen=True)
class HardLimits:
    """Tier 2 — binding.  Exceeding any of these halts trading."""

    max_drawdown_pct: float = 15.0
    max_daily_loss: float = 5_000.0
    max_daily_trades: int = 200


@dataclass
class BotState:
    drawdown_pct: float = 0.0
    position_notional: float = 0.0
    effective_leverage: float = 0.0
    margin_buffer: float = float("inf")
    daily_loss: float = 0.0
    daily_trade_count: int = 0


def check_soft_limits(limits: SoftLimits, state: BotState) -> list[str]:
    warnings: list[str] = []
    if state.drawdown_pct > limits.max_drawdown_pct:
        warnings.append(
            f"drawdown {state.drawdown_pct:.2f}% exceeds soft limit "
            f"{limits.max_drawdown_pct:.2f}%"
        )
    if state.position_notional > limits.max_position_notional:
        warnings.append(
            f"position notional {state.position_notional:.2f} exceeds "
            f"{limits.max_position_notional:.2f}"
        )
    if state.effective_leverage > limits.max_leverage:
        warnings.append(
            f"leverage {state.effective_leverage:.2f}x exceeds "
            f"{limits.max_leverage:.2f}x"
        )
    if state.margin_buffer < limits.min_margin_buffer:
        warnings.append(
            f"margin buffer {state.margin_buffer:.2f}x below "
            f"{limits.min_margin_buffer:.2f}x"
        )
    return warnings


def enforce_hard_limits(limits: HardLimits, state: BotState) -> str | None:
    """Non-None means STOP TRADING NOW."""
    if state.drawdown_pct > limits.max_drawdown_pct:
        return (
            f"HALT: drawdown {state.drawdown_pct:.2f}% exceeded hard limit "
            f"{limits.max_drawdown_pct:.2f}%"
        )
    if state.daily_loss > limits.max_daily_loss:
        return f"HALT: daily loss {state.daily_loss:.2f} exceeded limit"
    if state.daily_trade_count > limits.max_daily_trades:
        return f"HALT: daily trade count {state.daily_trade_count} exceeded limit"
    return None


@dataclass
class CircuitBreaker:
    """Both tiers together, with a latching halt.

    Once tripped it stays tripped until explicitly reset, so a momentary
    recovery in a noisy metric cannot silently re-arm a strategy that already
    breached a hard limit.
    """

    soft: SoftLimits = field(default_factory=SoftLimits)
    hard: HardLimits = field(default_factory=HardLimits)
    log: Callable[[str], None] = field(default=lambda message: None, repr=False)
    halted_reason: str | None = field(default=None, init=False)

    @property
    def halted(self) -> bool:
        return self.halted_reason is not None

    def evaluate(self, state: BotState) -> list[str]:
        warnings = check_soft_limits(self.soft, state)
        for warning in warnings:
            self.log(f"soft limit: {warning}")
        breach = enforce_hard_limits(self.hard, state)
        if breach is not None and self.halted_reason is None:
            self.halted_reason = breach
            self.log(breach)
        return warnings

    def assert_can_trade(self) -> None:
        if self.halted_reason is not None:
            raise CircuitBreakerTripped(self.halted_reason)

    def reset(self) -> None:
        self.halted_reason = None


# ── Heartbeat kill switch ────────────────────────────────────────


class KillSwitch:
    """Dead-man switch owned by the bot.

    The API deliberately provides none (``gotchas.md`` §13).  When the strategy
    loop stalls past ``max_silence_seconds`` every open order is cancelled.

    Cancellation is VERIFIED, not assumed: ``cancel_all`` must re-read pending
    orders and return the surviving ones.  A kill switch that reports success
    without confirming is worse than none, because it hides live exposure.
    """

    def __init__(
        self,
        max_silence_seconds: float,
        cancel_all: Callable[[], Sequence[object]],
        *,
        log: Callable[[str], None] = lambda message: None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_silence_seconds <= 0:
            raise NormalizationError("max_silence_seconds must be positive")
        self._max_silence = float(max_silence_seconds)
        self._cancel_all = cancel_all
        self._log = log
        self._clock = clock
        self._last_beat = clock()
        self._armed = True
        self.fired = False
        self.verified = False

    @property
    def armed(self) -> bool:
        return self._armed

    def heartbeat(self) -> None:
        self._last_beat = self._clock()

    def silence_seconds(self) -> float:
        return self._clock() - self._last_beat

    def check(self) -> bool:
        """Fire if the loop has gone quiet.  Returns True if it fired."""
        if not self._armed:
            return False
        silence = self.silence_seconds()
        if silence <= self._max_silence:
            return False
        self.trigger(f"heartbeat timeout — {silence:.1f}s since last beat")
        return True

    def trigger(self, reason: str) -> None:
        """Cancel everything, then PROVE it.

        Leaves the switch armed on failure: the exposure is real and a later
        attempt must still be able to fire.
        """
        if not self._armed:
            return
        self._log(f"KILL SWITCH: {reason}")
        self.fired = True
        survivors = self._cancel_all()
        if survivors:
            self.verified = False
            self._log(
                f"kill switch: cancellation NOT verified — {len(survivors)} "
                "order(s) still resting"
            )
            raise CircuitBreakerTripped(
                f"kill switch fired but {len(survivors)} order(s) survived "
                "cancellation"
            )
        self.verified = True
        self._armed = False
        self._log("kill switch: all orders cancelled and verified")

    def disarm(self) -> None:
        self._armed = False

    def rearm(self) -> None:
        self._armed = True
        self.fired = False
        self.verified = False
        self._last_beat = self._clock()


@dataclass
class ShutdownHandler:
    """SIGINT/SIGTERM cancel-all with a timeout and a non-zero exit code.

    Installed by the adapter, not by strategies, so every strategy inherits it.
    """

    kill_switch: KillSwitch
    timeout_seconds: float = 20.0
    log: Callable[[str], None] = field(default=lambda message: None, repr=False)
    exit_code: int = field(default=0, init=False)
    handled: list[str] = field(default_factory=list, init=False)
    _previous: dict[int, object] = field(default_factory=dict, init=False, repr=False)

    def handle(self, signal_name: str) -> int:
        """Run the shutdown sequence.  Returns the intended exit code."""
        self.handled.append(signal_name)
        started = time.monotonic()
        try:
            self.kill_switch.trigger(f"{signal_name} — shutting down")
        except Exception as exc:  # noqa: BLE001 - must not mask a failed cancel
            self.log(f"shutdown: cancellation FAILED — {exc}")
            self.exit_code = 1
            return self.exit_code
        if time.monotonic() - started > self.timeout_seconds:
            self.log("shutdown: cancellation exceeded its timeout")
            self.exit_code = 1
        return self.exit_code

    def install(self) -> None:  # pragma: no cover - process-level side effect
        for signum, name in (
            (signal.SIGINT, "SIGINT"),
            (signal.SIGTERM, "SIGTERM"),
        ):
            self._previous[signum] = signal.getsignal(signum)
            signal.signal(
                signum,
                lambda _s, _f, _name=name: raise_system_exit(self.handle(_name)),
            )

    def uninstall(self) -> None:  # pragma: no cover - process-level side effect
        for signum, previous in self._previous.items():
            signal.signal(signum, previous)  # type: ignore[arg-type]
        self._previous.clear()


def raise_system_exit(code: int) -> None:  # pragma: no cover - trivial
    raise SystemExit(code)


# ── Serialised object-sensitive operations ───────────────────────


class SerialGate:
    """Serialises coin/gas-object-sensitive operations.

    Parallel deposits race on Sui objects and fail with version/equivocation
    errors, so deposits (and anything else touching the same coin objects) are
    funnelled through one gate.  Re-entrancy is an error, not a queue: the
    caller should await the previous operation, and silently serialising would
    hide a concurrency bug in the strategy.
    """

    def __init__(self) -> None:
        self._busy = False

    def __enter__(self) -> "SerialGate":
        if self._busy:
            raise CircuitBreakerTripped(
                "concurrent coin-object operation refused: Sui object versions "
                "race. Serialise deposits/withdrawals."
            )
        self._busy = True
        return self

    def __exit__(self, *_exc: object) -> None:
        self._busy = False
