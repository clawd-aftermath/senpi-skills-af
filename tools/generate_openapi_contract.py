#!/usr/bin/env python3
"""Extract the read-only Aftermath runtime contract from a local OpenAPI file.

The generator never fetches the network.  Downloading or otherwise supplying
the source spec is an explicit caller step, which keeps CI reproducible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

CANONICAL_SPEC_SHA256 = "fbc76c20bb3581a638d59ff5afc2c1dfd2f47d7453f14327aab8a8e5d34ca9f4"
SOURCE_URL = "https://aftermath.finance/api/openapi/spec.json"
SELECTED_PATHS = (
    "/api/perpetuals/markets",
    "/api/perpetuals/markets/prices",
    "/api/perpetuals/market/candle-history",
    "/api/perpetuals/market/funding-history",
    "/api/perpetuals/accounts",
    "/api/perpetuals/accounts/owned",
    "/api/perpetuals/accounts/positions",
    "/api/ccxt/myPendingOrders",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def collect_schema_refs(value: Any, names: set[str]) -> None:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            names.add(ref.rsplit("/", 1)[-1])
        for child in value.values():
            collect_schema_refs(child, names)
    elif isinstance(value, list):
        for child in value:
            collect_schema_refs(child, names)


def build_contract(spec: dict[str, Any]) -> dict[str, Any]:
    paths = spec.get("paths")
    schemas = spec.get("components", {}).get("schemas")
    if not isinstance(paths, dict) or not isinstance(schemas, dict):
        raise ValueError("OpenAPI source is missing paths/components.schemas")
    missing = [path for path in SELECTED_PATHS if path not in paths]
    if missing:
        raise ValueError(f"OpenAPI source is missing selected paths: {missing}")
    selected = {path: paths[path] for path in SELECTED_PATHS}
    names: set[str] = set()
    collect_schema_refs(selected, names)
    pending = list(names)
    while pending:
        name = pending.pop()
        if name not in schemas:
            raise ValueError(f"referenced schema is missing: {name}")
        before = set(names)
        collect_schema_refs(schemas[name], names)
        pending.extend(sorted(names - before))
    canonical_sha = hashlib.sha256(canonical_bytes(spec)).hexdigest()
    return {
        "contractVersion": "aftermath-read-v1",
        "source": {
            "url": SOURCE_URL,
            "canonicalSha256": canonical_sha,
            "openapi": spec.get("openapi"),
            "info": spec.get("info"),
        },
        "paths": selected,
        "schemas": {name: schemas[name] for name in sorted(names)},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path, help="local OpenAPI JSON source")
    parser.add_argument("output", type=Path, help="generated selected contract")
    parser.add_argument(
        "--expected-sha",
        default=CANONICAL_SPEC_SHA256,
        help="expected canonical JSON SHA-256; use '' only for an intentional refresh",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate that output already equals the generated contract",
    )
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    contract = build_contract(spec)
    actual = contract["source"]["canonicalSha256"]
    if args.expected_sha and actual != args.expected_sha:
        raise SystemExit(
            f"OpenAPI SHA mismatch: expected {args.expected_sha}, received {actual}"
        )
    generated = json.dumps(contract, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.exists():
            raise SystemExit(f"generated contract is missing: {args.output}")
        if args.output.read_text(encoding="utf-8") != generated:
            raise SystemExit(
                "generated contract is stale; rerun without --check and review the diff"
            )
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(generated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
