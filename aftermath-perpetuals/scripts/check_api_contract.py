#!/usr/bin/env python3
"""Validate Aftermath API references against the post-relaunch OpenAPI spec."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_SPEC_URL = (
    "https://v2-preview.aftermath.finance/api/openapi/spec.json"
)
API_FAMILIES = (
    "ccxt",
    "coins",
    "gas-pool",
    "perpetuals",
    "referrals",
    "rewards",
    "zklogin",
)
ENDPOINT_RE = re.compile(
    rf"(/api/(?:{'|'.join(re.escape(family) for family in API_FAMILIES)})"
    r"[A-Za-z0-9_./{}*-]*)"
)
OLD_HOST_RE = re.compile(
    r"(?:https|wss)://aftermath\.finance/(?:api|docs)"
)
DEPRECATED_CODE_FIELDS = (
    "stopLossIndexPrice",
    "takeProfitIndexPrice",
    "gasPriceTakerFee",
    "gasPriceTwapPeriodMs",
    "zScoreThreshold",
    "forceCancelFee",
)
TEXT_SUFFIXES = {
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
CODE_SUFFIXES = {".js", ".mjs", ".py", ".sh", ".ts", ".tsx"}
CRITICAL_REQUEST_KEYS = {
    "/api/perpetuals/all-markets": {"collateralCoinType"},
    "/api/perpetuals/market/candle-history": {
        "fromTimestamp",
        "marketId",
        "resolution",
        "toTimestamp",
    },
    "/api/perpetuals/markets": set(),
    "/api/perpetuals/markets/prices": {"marketIds"},
}
SL_TP_ORDER_SCHEMAS = (
    "ApiPerpetualsLimitOrderBody",
    "ApiPerpetualsMarketOrderBody",
)


def load_spec(source: str) -> dict[str, Any]:
    path = Path(source)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    request = urllib.request.Request(
        source,
        headers={"User-Agent": "senpi-skills-af-contract-check/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def endpoint_matches(endpoint: str, openapi_paths: set[str]) -> bool:
    if endpoint in openapi_paths:
        return True

    for candidate in openapi_paths:
        pattern = "/".join(
            "[^/]+"
            if segment.startswith("{") and segment.endswith("}")
            else re.escape(segment)
            for segment in candidate.split("/")
        )
        if re.fullmatch(pattern, endpoint):
            return True
    return False


def resolve_schema(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if not reference:
        return schema
    prefix = "#/components/schemas/"
    if not reference.startswith(prefix):
        raise ValueError(f"unsupported schema reference: {reference}")
    return spec["components"]["schemas"][reference[len(prefix):]]


def validate_critical_request_keys(
    spec: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    for endpoint, supplied_keys in CRITICAL_REQUEST_KEYS.items():
        operation = spec.get("paths", {}).get(endpoint, {}).get("post", {})
        schema = (
            operation.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema", {})
        )
        if not schema:
            failures.append(f"{endpoint}: missing JSON request schema")
            continue
        try:
            resolved = resolve_schema(spec, schema)
        except (KeyError, ValueError) as error:
            failures.append(f"{endpoint}: {error}")
            continue
        required = set(resolved.get("required", []))
        missing = sorted(required - supplied_keys)
        if missing:
            failures.append(
                f"{endpoint}: critical example omits required keys {missing}"
            )
    return failures


def combined_properties(
    spec: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    properties = dict(schema.get("properties", {}))
    for part in schema.get("allOf", []):
        resolved = resolve_schema(spec, part)
        properties.update(combined_properties(spec, resolved))
    return properties


def validate_relaunch_semantics(spec: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    schemas = spec.get("components", {}).get("schemas", {})

    sl_tp = schemas.get("ApiSlTpDetails", {})
    sl_tp_properties = set(sl_tp.get("properties", {}))
    expected_sl_tp = {
        "stopLossPrice",
        "takeProfitPrice",
        "triggerPriceType",
    }
    missing_sl_tp = sorted(expected_sl_tp - sl_tp_properties)
    if missing_sl_tp:
        failures.append(
            f"ApiSlTpDetails: missing relaunch fields {missing_sl_tp}"
        )
    trigger_description = (
        sl_tp.get("properties", {})
        .get("triggerPriceType", {})
        .get("description", "")
    )
    for expected in ("0` = index", "1` = book mid", "2` = mark"):
        if expected not in trigger_description:
            failures.append(
                "ApiSlTpDetails.triggerPriceType: enum description changed; "
                f"missing {expected!r}"
            )

    for schema_name in SL_TP_ORDER_SCHEMAS:
        schema = schemas.get(schema_name, {})
        if "slTp" not in combined_properties(spec, schema):
            failures.append(
                f"{schema_name}: order body no longer exposes slTp"
            )

    market_params = schemas.get("PerpetualsMarketParams", {})
    priority_fee = market_params.get("properties", {}).get(
        "priorityTakerFee"
    )
    if not priority_fee:
        failures.append(
            "PerpetualsMarketParams: missing priorityTakerFee"
        )
    else:
        field_type = priority_fee.get("type", [])
        if not isinstance(field_type, list) or "null" not in field_type:
            failures.append(
                "PerpetualsMarketParams.priorityTakerFee is no longer nullable"
            )
        if "priorityTakerFee" in market_params.get("required", []):
            failures.append(
                "PerpetualsMarketParams.priorityTakerFee became required"
            )

    return failures


def iter_text_files(repo_root: Path):
    for path in repo_root.rglob("*"):
        if (
            path.is_file()
            and ".git" not in path.parts
            and path.suffix.lower() in TEXT_SUFFIXES
            and path.name != Path(__file__).name
        ):
            yield path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default=DEFAULT_SPEC_URL)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    args = parser.parse_args()

    spec = load_spec(args.spec)
    canonical_spec = json.dumps(
        spec, separators=(",", ":"), sort_keys=True
    ).encode()
    spec_sha256 = hashlib.sha256(canonical_spec).hexdigest()
    spec_source = (
        f"local:{Path(args.spec).resolve()}"
        if Path(args.spec).exists()
        else f"live:{args.spec}"
    )
    openapi_paths = set(spec.get("paths", {}))
    if not openapi_paths:
        print("OpenAPI spec contains no paths", file=sys.stderr)
        return 2

    failures: list[str] = []
    checked_endpoints: set[str] = set()
    skipped_references = 0

    for path in iter_text_files(args.repo_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(args.repo_root)

        for match in OLD_HOST_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            failures.append(
                f"{relative}:{line}: legacy API/docs host {match.group(0)}"
            )

        if path.suffix.lower() in CODE_SUFFIXES:
            for field in DEPRECATED_CODE_FIELDS:
                for match in re.finditer(rf"\b{re.escape(field)}\b", text):
                    line = text.count("\n", 0, match.start()) + 1
                    failures.append(
                        f"{relative}:{line}: deprecated relaunch field {field}"
                    )

        for match in ENDPOINT_RE.finditer(text):
            endpoint = match.group(1).rstrip(".,;:`)")
            if (
                "*" in endpoint
                or endpoint.endswith("/")
                or endpoint in {"/api/perpetuals", "/api/ccxt"}
            ):
                skipped_references += 1
                continue
            checked_endpoints.add(endpoint)
            if not endpoint_matches(endpoint, openapi_paths):
                line = text.count("\n", 0, match.start()) + 1
                failures.append(
                    f"{relative}:{line}: endpoint absent from relaunch spec: "
                    f"{endpoint}"
                )

    failures.extend(validate_critical_request_keys(spec))
    failures.extend(validate_relaunch_semantics(spec))

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    print(
        f"Validated path existence for {len(checked_endpoints)} endpoint "
        f"references against {len(openapi_paths)} OpenAPI paths; "
        f"skipped {skipped_references} family/wildcard references. "
        f"Validated required request keys for "
        f"{len(CRITICAL_REQUEST_KEYS)} critical payloads and relaunch "
        f"SL/TP/priority-fee schema invariants. Source: {spec_source}; "
        f"canonical JSON SHA-256: {spec_sha256}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
