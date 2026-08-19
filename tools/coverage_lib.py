#!/usr/bin/env python3
"""Deterministic, offline inventory and coverage generation for Aftermath.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "strategies"
OVERLAY = ROOT / "aftermath-overlay"
CATALOG = OVERLAY / "catalog"

CLASSIFICATIONS = (
    "supported",
    "needs-field-mapping",
    "needs-derived-data",
    "blocked-market",
    "blocked-runtime-semantics",
)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _scalar(text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*[\"']?([^\"'#\n]+)", text)
    return match.group(1).strip() if match else None


def _assets(text: str) -> list[str]:
    match = re.search(r"(?m)^\s{2}assets:\s*(\[[^\n]*\])", text)
    if not match:
        return []
    try:
        parsed = ast.literal_eval(match.group(1))
    except (SyntaxError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


@dataclass(frozen=True)
class Package:
    id: str
    version: str
    manifest: str
    instances: tuple[str, ...]
    assets: tuple[str, ...]
    source_sha256: str
    source_text: str
    code_literals: tuple[str, ...]

    def inventory_record(self) -> dict[str, Any]:
        return {
            "assets": list(self.assets),
            "id": self.id,
            "instance_count": len(self.instances),
            "instances": list(self.instances),
            "manifest": self.manifest,
            "source_sha256": self.source_sha256,
            "version": self.version,
        }


def inventory() -> list[Package]:
    packages: list[Package] = []
    seen: set[str] = set()
    for manifest in sorted(STRATEGIES.glob("*/strategy.yaml")):
        text = manifest.read_text(encoding="utf-8")
        package_id = _scalar(text, "id") or manifest.parent.name
        if package_id != manifest.parent.name:
            raise ValueError(f"{manifest}: id {package_id!r} does not match directory")
        if package_id in seen:
            raise ValueError(f"duplicate strategy id: {package_id}")
        seen.add(package_id)
        runtime_files = tuple(
            str(path.relative_to(ROOT))
            for path in sorted(manifest.parent.glob("*/runtime.yaml"))
        )
        source_files = sorted(
            path for path in manifest.parent.rglob("*") if path.is_file()
        )
        source_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace") for path in source_files
        )
        code_literals: set[str] = set()
        for path in (p for p in source_files if p.suffix == ".py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                raise ValueError(f"{path}: cannot inventory invalid Python: {exc}") from exc
            docstring_nodes: set[int] = set()
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if (
                    isinstance(body, list)
                    and body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    docstring_nodes.add(id(body[0].value))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstring_nodes
                ):
                    code_literals.add(node.value)
        packages.append(
            Package(
                id=package_id,
                version=_scalar(text, "version") or "unknown",
                manifest=str(manifest.relative_to(ROOT)),
                instances=runtime_files,
                assets=tuple(_assets(text)),
                source_sha256=sha256(manifest),
                source_text=source_text,
                code_literals=tuple(sorted(code_literals)),
            )
        )
    return packages


def classify_detail(package: Package, rules: dict[str, Any]) -> dict[str, Any]:
    package_id = package.id
    runtime_blocks = rules["blocked_runtime_semantics"]
    if package_id in runtime_blocks:
        return {
            "classification": "blocked-runtime-semantics",
            "matched_marker": package_id,
            "reasons": [runtime_blocks[package_id]],
            "rule_id": "explicit-runtime-block",
        }

    literals_lower = {literal.lower() for literal in package.code_literals}
    markers = [
        marker
        for marker in rules["derived_data_markers"]
        if any(marker.lower() in literal for literal in literals_lower)
    ]
    if markers:
        return {
            "classification": "needs-derived-data",
            "matched_marker": sorted(markers),
            "reasons": [
                f"Requires Senpi-derived data marker: {marker}"
                for marker in sorted(markers)
            ],
            "rule_id": "derived-data-literal",
        }

    active = {symbol.upper() for symbol in rules["active_market_symbols"]}
    declared = {asset.split(":", 1)[-1].upper() for asset in package.assets}
    if not declared:
        return {
            "classification": "blocked-market",
            "matched_marker": "dynamic-universe",
            "reasons": [
                "Dynamic/universe-ranked package cannot fail open when the retired "
                "preview fixture has only one active market."
            ],
            "rule_id": "market-dynamic-fail-closed",
        }
    unavailable = sorted(declared - active)
    if unavailable:
        return {
            "classification": "blocked-market",
            "matched_marker": unavailable,
            "reasons": [
                f"Unavailable declared market: {symbol}" for symbol in unavailable
            ],
            "rule_id": "market-unavailable",
        }

    if package_id in rules["supported"]:
        return {
            "classification": "supported",
            "matched_marker": package_id,
            "reasons": ["Explicitly enabled by reviewed coverage rules."],
            "rule_id": "explicit-supported",
        }
    if package_id in rules["field_mapping_candidates"]:
        return {
            "classification": "needs-field-mapping",
            "matched_marker": package_id,
            "reasons": [
            "Market is available, but scanner fields and runtime semantics must be "
            "ported to the typed Aftermath interface."
            ],
            "rule_id": "explicit-field-mapping-candidate",
        }
    return {
        "classification": "blocked-runtime-semantics",
        "matched_marker": package_id,
        "reasons": [
            "Package has no explicit supported or field-mapping rule; fail closed."
        ],
        "rule_id": "unclassified-fail-closed",
    }


def classify(package: Package, rules: dict[str, Any]) -> tuple[str, list[str]]:
    detail = classify_detail(package, rules)
    return detail["classification"], detail["reasons"]


def build(upstream_ref_override: str | None = None) -> dict[str, bytes]:
    rules = json.loads((OVERLAY / "coverage-rules.json").read_text())
    upstream_ref = upstream_ref_override or (ROOT / "UPSTREAM_REF").read_text().strip()
    packages = inventory()
    records: list[dict[str, Any]] = []
    for package in packages:
        detail = classify_detail(package, rules)
        classification = detail["classification"]
        if classification not in CLASSIFICATIONS:
            raise ValueError(f"invalid classification: {classification}")
        record = package.inventory_record()
        record.update(
            {
                "classification": classification,
                "enabled": classification == "supported",
                "matched_marker": detail["matched_marker"],
                "reasons": detail["reasons"],
                "rule_id": detail["rule_id"],
                "upstream_ref": upstream_ref,
            }
        )
        records.append(record)

    enabled = [record for record in records if record["enabled"]]
    blocked = [record for record in records if not record["enabled"]]
    counts = {name: 0 for name in CLASSIFICATIONS}
    for record in records:
        counts[record["classification"]] += 1
    instance_count = sum(record["instance_count"] for record in records)

    if len(records) != len(enabled) + len(blocked):
        raise AssertionError("source packages != enabled + blocked")
    if {r["id"] for r in records} != {r["id"] for r in enabled + blocked}:
        raise AssertionError("enabled/blocked package partition is not exhaustive")
    allowed_enabled = set(rules["supported"])
    if not {record["id"] for record in enabled} <= allowed_enabled:
        raise AssertionError("enabled packages must be explicitly supported")

    meta = {
        "classification_counts": counts,
        "enabled_count": len(enabled),
        "instance_count": instance_count,
        "invariant": {
            "enabled_plus_blocked": len(enabled) + len(blocked),
            "holds": len(records) == len(enabled) + len(blocked),
            "source_packages": len(records),
        },
        "source_package_count": len(records),
        "upstream_ref": upstream_ref,
    }
    inventory_doc = {"meta": meta, "packages": [p.inventory_record() for p in packages]}
    coverage_doc = {"meta": meta, "packages": records}
    enabled_doc = {"meta": meta, "packages": enabled}
    blocked_doc = {"meta": meta, "packages": blocked}
    summary_lines = [
        "# Generated Aftermath coverage",
        "",
        f"- Upstream: `{upstream_ref}`",
        f"- Source packages: {len(records)}",
        f"- Runtime instances: {instance_count}",
        f"- Enabled: {len(enabled)}",
        f"- Blocked: {len(blocked)}",
        f"- Invariant: `{len(records)} == {len(enabled)} + {len(blocked)}`",
        "",
        "## Classifications",
        "",
    ]
    summary_lines.extend(f"- `{key}`: {counts[key]}" for key in CLASSIFICATIONS)
    summary_lines.extend(
        [
            "",
            "Generated by `tools/generate_coverage.py`; do not edit catalogs by hand.",
            "",
        ]
    )
    field_lines = [
        "# Generated field coverage",
        "",
        "Exact mappings and explicit gaps for the initial BTC candidates.",
        "",
    ]
    mapping_dir = OVERLAY / "field-mappings"
    for path in sorted(mapping_dir.glob("*.json")):
        mapping = json.loads(path.read_text())
        field_lines.extend([f"## {mapping['strategy']}", ""])
        field_lines.append(
            "Sources: "
            + ", ".join(f"`{source}`" for source in mapping["source_scanners"])
        )
        field_lines.extend(
            [
                "",
                "| Consumed source field | Aftermath V2 mapping or gap | Status |",
                "| --- | --- | --- |",
            ]
        )
        for field in mapping["fields"]:
            consumed = field["consumed"].replace("|", "\\|")
            aftermath = field["aftermath"].replace("|", "\\|")
            field_lines.append(
                f"| `{consumed}` | {aftermath} | `{field['status']}` |"
            )
        field_lines.append("")
    field_lines.append("Generated from `field-mappings/*.json`; do not hand-edit.\n")
    return {
        "inventory.json": canonical_json(inventory_doc),
        "coverage.json": canonical_json(coverage_doc),
        "enabled.json": canonical_json(enabled_doc),
        "blocked.json": canonical_json(blocked_doc),
        "SUMMARY.md": "\n".join(summary_lines).encode(),
        "FIELD_COVERAGE.md": "\n".join(field_lines).encode(),
    }
