"""Read-only stream snapshot/delta reconciliation state.

Network streaming is intentionally out of scope.  This state machine captures
the mandatory safety rule: after disconnect, deltas are rejected until a fresh
snapshot replaces local state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import ContractError


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
