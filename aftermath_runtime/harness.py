"""Run an unmodified upstream strategy scanner against Aftermath.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

This is the proof that the adapter approach works: an upstream ``scan.py``,
byte-for-byte as pinned, imported and executed with a ``ctx`` whose
``senpi_mcp`` is an Aftermath adapter.  The strategy is not edited, wrapped, or
special-cased — it just calls the tools it always called, and Aftermath answers.

The ``ctx`` surface is exactly what the upstream scan contract specifies:

===========================  ==========================================
``ctx.senpi_mcp.call_tool``  the adapter -- the ONLY way to fetch data
``ctx.state``                transactional history store (or ``None``)
``ctx.wallet``               the runtime's wallet address
``ctx.scanner_name``         this scanner's name
``ctx.interval_seconds``     this scanner's tick cadence
===========================  ==========================================

``ctx`` is frozen, ``ctx.state.append`` takes a dict, and state advances only on
a clean tick — a raising scan rolls its state back, matching upstream.

**This harness executes scanners, which are read-only and pure by contract.  It
never places an order.**  Signals a scan returns are data; acting on them is the
supervisor's job and no supervisor here is armed.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


class ScanState:
    """The upstream transactional history store.

    ``append`` is staged and only committed by :meth:`commit`, so an exception
    mid-tick discards the tick's state exactly as the runtime does.  A scanner
    that crashes must not leave a half-written dedup ledger behind.
    """

    def __init__(self, records: Sequence[Mapping[str, Any]] = (), max_count: int = 100):
        self._records: list[dict[str, Any]] = [dict(r) for r in records]
        self._staged: list[dict[str, Any]] = []
        self._max_count = max_count

    def last(self) -> dict[str, Any] | None:
        combined = self._records + self._staged
        return dict(combined[-1]) if combined else None

    def recent(self, count: int) -> list[dict[str, Any]]:
        combined = self._records + self._staged
        return [dict(r) for r in combined[-count:]]

    def append(self, record: Mapping[str, Any]) -> None:
        if not isinstance(record, Mapping):
            raise TypeError("ctx.state.append requires a dict")
        self._staged.append(dict(record))

    def __len__(self) -> int:
        return len(self._records) + len(self._staged)

    def commit(self) -> None:
        self._records.extend(self._staged)
        self._staged.clear()
        if len(self._records) > self._max_count:
            del self._records[: len(self._records) - self._max_count]

    def rollback(self) -> None:
        self._staged.clear()

    @property
    def records(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._records]


@dataclass(frozen=True)
class ScanContext:
    """The frozen ``ctx`` handed to ``scan(inputs, ctx)``."""

    senpi_mcp: Any
    wallet: str
    state: ScanState | None = None
    scanner_name: str = "aftermath"
    interval_seconds: int = 300
    max_leverage: float = 10.0
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def get(self, key: str, default: Any = None) -> Any:
        """Upstream scanners call ``ctx.get`` for optional runtime extras."""
        return self.extra.get(key, default)


def load_scanner(entrypoint: Path, module_name: str | None = None):
    """Import an upstream ``scan.py`` without editing it.

    Its sibling directory goes on ``sys.path`` first because scanners import
    their pure-maths module as a bare ``import scoring``.

    Those sibling modules are then EVICTED from ``sys.modules``.  Every strategy
    package ships its own ``scoring.py`` under the same name, so leaving the
    first one cached would silently hand strategy B strategy A's maths — and it
    would look like a working import, not an error.  The runtime supervises each
    scanner in its own process; this restores the same isolation in-process.
    """
    entrypoint = Path(entrypoint).resolve()
    if not entrypoint.is_file():
        raise FileNotFoundError(entrypoint)
    package_dir = entrypoint.parent
    sibling_names = {
        path.stem
        for path in package_dir.glob("*.py")
        if path.name != entrypoint.name
    }
    # Evict any same-named module cached from a previous package BEFORE the
    # import, and restore it afterwards, so each load resolves `import scoring`
    # to its own package's file.
    stashed = {
        name: sys.modules.pop(name)
        for name in sibling_names
        if name in sys.modules
    }
    before = set(sys.modules)
    sys.path.insert(0, str(package_dir))
    try:
        name = module_name or f"_af_scan_{abs(hash(str(entrypoint)))}"
        spec = importlib.util.spec_from_file_location(name, entrypoint)
        if spec is None or spec.loader is None:  # pragma: no cover
            raise ImportError(f"cannot import {entrypoint}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            _evict_siblings(before, package_dir)
        return module
    finally:
        try:
            sys.path.remove(str(package_dir))
        except ValueError:  # pragma: no cover
            pass
        sys.modules.update(stashed)


def _evict_siblings(before: set[str], package_dir: Path) -> None:
    for name in set(sys.modules) - before:
        module = sys.modules.get(name)
        origin = getattr(module, "__file__", None)
        if not origin:
            continue
        try:
            same_package = Path(origin).resolve().parent == package_dir
        except OSError:  # pragma: no cover
            continue
        if same_package and not name.startswith("_af_scan_"):
            del sys.modules[name]


def run_scan(
    entrypoint: Path,
    inputs: Mapping[str, Any],
    adapter: Any,
    *,
    wallet: str = "",
    state: ScanState | None = None,
    scanner_name: str = "aftermath",
    interval_seconds: int = 300,
) -> list[dict[str, Any]]:
    """Run one tick of an upstream scanner against an Aftermath adapter.

    Returns the emitted signals.  State commits only on a clean tick.
    """
    module = load_scanner(entrypoint)
    scan = getattr(module, "scan", None)
    if not callable(scan):
        raise AttributeError(f"{entrypoint} exports no callable scan(inputs, ctx)")
    context = ScanContext(
        senpi_mcp=adapter,
        wallet=wallet or (adapter.config.wallet_address or ""),
        state=state,
        scanner_name=scanner_name,
        interval_seconds=interval_seconds,
    )
    try:
        signals = scan(dict(inputs), context)
    except BaseException:
        if state is not None:
            state.rollback()
        raise
    if state is not None:
        state.commit()
    if signals is None:
        return []
    if not isinstance(signals, list):
        raise TypeError(
            f"{entrypoint} returned {type(signals).__name__}; scan() must return "
            "a list of signal dicts"
        )
    return signals
