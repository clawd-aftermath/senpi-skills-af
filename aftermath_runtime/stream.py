"""Read-only stream snapshot/delta reconciliation state.

Network streaming is intentionally out of scope.  This state machine captures
the mandatory safety rule: after disconnect, deltas are rejected until a fresh
snapshot replaces local state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import ContractError

CANDLE_STREAM_PATH = "/api/perpetuals/ws/updates"
CANDLE_RESOLUTIONS = frozenset(
    {"1m", "5m", "15m", "30m", "1h", "4h", "12h", "1d", "3d", "1w", "1mo"}
)


def market_candles_subscription(
    market_id: str, resolution: str
) -> dict[str, object]:
    """Build the v3 general-updates WebSocket candle subscription."""
    if not isinstance(market_id, str) or not market_id:
        raise ContractError("marketId must be a non-empty string")
    if resolution not in CANDLE_RESOLUTIONS:
        raise ContractError(f"unsupported candle resolution: {resolution!r}")
    return {
        "action": "subscribe",
        "subscriptionType": {
            "marketCandles": {"marketId": market_id, "interval": resolution}
        },
    }


@dataclass
class SnapshotStreamState:
    sequence: int | None = None
    synced: bool = False
    rows: dict[str, Mapping[str, Any]] = field(default_factory=dict)

    def disconnected(self) -> None:
        self.synced = False

    def replace_snapshot(
        self, *, sequence: int, rows: Mapping[str, Mapping[str, Any]]
    ) -> None:
        if sequence < 0:
            raise ContractError("snapshot sequence cannot be negative")
        self.sequence = sequence
        self.rows = dict(rows)
        self.synced = True

    def apply_delta(
        self, *, sequence: int, updates: Mapping[str, Mapping[str, Any] | None]
    ) -> None:
        if not self.synced or self.sequence is None:
            raise ContractError("fresh snapshot required before stream deltas")
        if sequence != self.sequence + 1:
            self.synced = False
            raise ContractError(
                f"stream sequence gap: expected {self.sequence + 1}, received {sequence}"
            )
        for key, value in updates.items():
            if value is None:
                self.rows.pop(key, None)
            else:
                self.rows[key] = value
        self.sequence = sequence
