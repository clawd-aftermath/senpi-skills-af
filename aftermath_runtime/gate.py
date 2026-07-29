"""Runtime promotion gate for the read-only Aftermath overlay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .errors import ContractError, WriteDenied

DEFAULT_DRIFT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "known-drift.json"


def assert_runtime_enablement(
    config: Mapping[str, Any], *, drift_path: Path = DEFAULT_DRIFT_PATH
) -> None:
    """Allow only the implemented shadow/deny mode.

    Unresolved machine-readable contract drift is checked before the structural
    write denial so a promotion attempt reports the concrete upstream blocker.
    """
    shadow_only = (
        config.get("mode") == "shadow" and config.get("write_policy") == "deny"
    )
    if shadow_only:
        return
    drift = json.loads(drift_path.read_text(encoding="utf-8"))
    unresolved = [
        entry
        for entry in drift.get("entries", [])
        if entry.get("blocking") is True and entry.get("status") == "unresolved"
    ]
    if unresolved:
        endpoints = sorted(str(entry.get("endpoint")) for entry in unresolved)
        raise ContractError(
            f"runtime promotion blocked by unresolved contract drift: {endpoints}"
        )
    raise WriteDenied("only aftermath/v1 shadow mode with write_policy=deny is implemented")
