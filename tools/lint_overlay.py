#!/usr/bin/env python3
"""Offline policy lint for generated coverage and runnable packages.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from coverage_lib import ROOT


FORBIDDEN_RUNNABLE = (
    re.compile(r"\bsenpi_mcp\b", re.I),
    re.compile(r"\bopenclaw\s+senpi\b", re.I),
    re.compile(r"\bxyz:", re.I),
    re.compile(r"\bstrategy_get_clearinghouse_state\b"),
    re.compile(r"\bmarket_get_asset_data\b"),
    re.compile(r"\bapi\.hyperliquid\.xyz\b", re.I),
)
FORBIDDEN_ANY_OVERLAY = (
    re.compile(r"\bapi\.hyperliquid\.xyz\b", re.I),
    re.compile(r"\bopenclaw\s+senpi\b", re.I),
)
NETWORK_IMPORTS = re.compile(
    r"(?m)^\s*(?:from|import)\s+(?:requests|urllib|httpx|aiohttp|socket)\b"
)


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    if "MIT License" not in license_text or "Senpi" not in license_text:
        fail("root MIT/Senpi attribution is missing")

    upstream = (ROOT / "UPSTREAM_REF").read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", upstream):
        fail("UPSTREAM_REF must be a full 40-character SHA")
    head_base = subprocess.run(
        ["git", "cat-file", "-e", f"{upstream}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if head_base.returncode:
        fail(f"UPSTREAM_REF is not present in repository history: {upstream}")
    source_diff = subprocess.run(
        ["git", "diff", "--name-only", upstream, "--", "strategies"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if source_diff:
        fail(f"overlay modifies upstream strategy sources:\n{source_diff}")

    current_apache: set[str] = set()
    for path in (ROOT / "strategies").rglob("*.py"):
        if "Apache-2.0" in path.read_text(encoding="utf-8", errors="replace"):
            current_apache.add(str(path.relative_to(ROOT)))
    pinned_paths = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", upstream, "strategies"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    pinned_apache: set[str] = set()
    for relative in (path for path in pinned_paths if path.endswith(".py")):
        source = subprocess.run(
            ["git", "show", f"{upstream}:{relative}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        if "Apache-2.0" in source:
            pinned_apache.add(relative)
    if not current_apache:
        fail("expected upstream per-file Apache-2.0 notices")
    if current_apache != pinned_apache:
        fail(
            "Apache-2.0 attribution set drifted:\n"
            f"missing={sorted(pinned_apache - current_apache)}\n"
            f"added={sorted(current_apache - pinned_apache)}"
        )

    policy_files: set[Path] = set()
    for folder in (
        ROOT / "aftermath-runnable",
        ROOT / "aftermath-overlay",
        ROOT / "tools",
        ROOT / "tests",
    ):
        policy_files.update(path for path in folder.rglob("*") if path.is_file())
    allowed_policy_definition = {ROOT / "tools/lint_overlay.py"}
    for path in sorted(policy_files - allowed_policy_definition):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in FORBIDDEN_ANY_OVERLAY:
            if pattern.search(text):
                fail(f"{path}: forbidden overlay pattern {pattern.pattern!r}")
    runnable_files = {
        path
        for path in (ROOT / "aftermath-runnable").rglob("*")
        if path.is_file()
    }
    runnable_files.add(ROOT / "aftermath-overlay/catalog/enabled.json")
    for path in sorted(runnable_files):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in FORBIDDEN_RUNNABLE:
            if pattern.search(text):
                fail(f"{path}: forbidden runnable pattern {pattern.pattern!r}")

    for folder in (ROOT / "tools", ROOT / "tests"):
        for path in sorted(folder.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            if NETWORK_IMPORTS.search(text):
                fail(f"{path}: generation/test tooling must be network-free")

    coverage = json.loads(
        (ROOT / "aftermath-overlay/catalog/coverage.json").read_text()
    )
    meta = coverage["meta"]
    invariant = meta["invariant"]
    if not invariant["holds"]:
        fail("catalog partition invariant is false")
    if invariant["source_packages"] != invariant["enabled_plus_blocked"]:
        fail("source != enabled + blocked")
    print(
        f"lint ok: {len(current_apache)} exact Apache-noticed Python files; "
        f"{invariant['source_packages']} packages partitioned"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
