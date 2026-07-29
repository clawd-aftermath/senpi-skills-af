#!/usr/bin/env python3
"""Validate the immutable Aftermath skills contract without network access.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "aftermath-skills-v3-contract.json"
PROVENANCE_PATH = ROOT / "aftermath-overlay" / "provenance.json"
PIN_PATH = ROOT / "AFTERMATH_SKILLS_REF"

EXPECTED_COMMIT = "5b614db62dcd2e58f442e93661f608fe7b073c32"
EXPECTED_FILES = {
    "skills/api/SKILL.md": "f2d0bcb48b53781a1f7204b38aa92c4cfcce071e67d0bccaf8bede7a5b9f3c38",
    "skills/api/error-handling.md": "5cfb48e5aff3d5d2026511413433dd95487ab798876f3e102f350559d93c4e57",
    "skills/api/gotchas.md": "096e4054919de5b893952f73a6d1f9f7bdb45191400cf93919ecfa235b9e8bc1",
    "skills/api/monitoring-patterns.md": "7fd2b8779b57c6edea53aeed3e869458c9efb2831c15385b2195748608cf4323",
    "skills/api/native.md": "732cfecbfbfbb447a5c8c5e8759e0190d7cac5ec258847bbafd68ad9683353ea",
    "skills/api/safety-and-risk.md": "3b2317266eb84e33f965da09caabdd394b04d3a623ab034bc5f97b5c48759fa5",
}
EXPECTED_RESOLUTIONS = [
    "1m",
    "5m",
    "15m",
    "30m",
    "1h",
    "4h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1mo",
]
EXPECTED_IMPLEMENTATION_STATUS = {
    "builderCode": "not_implemented_blocked",
    "candles.history": "implemented_read_only",
    "candles.streamSubscription": "implemented_shape_only_no_network_client",
    "identifiers": "implemented_read_only",
    "isolatedMarginAllocation": "not_implemented_blocked",
    "preview": "parser_only_write_endpoints_blocked",
    "runtimeSafety.deadManAndSerialization": "not_implemented_blocked",
    "signingAndSubmit": "not_implemented_blocked",
    "slTp": "not_implemented_blocked",
}


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    source = contract["source"]
    expectations = contract["expectations"]
    skill_provenance = provenance["aftermath_skills"]

    if PIN_PATH.read_text(encoding="utf-8").strip() != EXPECTED_COMMIT:
        raise ValueError("AFTERMATH_SKILLS_REF drifted")
    if source["commit"] != EXPECTED_COMMIT:
        raise ValueError("skills contract commit drifted")
    if source["branch"] != "feat/v2-skills" or source["skillVersion"] != "3.0.0":
        raise ValueError("skills branch/version drifted")
    if (
        source["fileDigestAlgorithm"]
        != "sha256 of raw file bytes stored at the pinned git commit"
    ):
        raise ValueError("skills file digest algorithm drifted")
    if source["files"] != EXPECTED_FILES:
        raise ValueError("controlling skill file digests drifted")
    if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in EXPECTED_FILES.values()):
        raise ValueError("invalid source file digest")
    if expectations["canonicalSurfacePrefix"] != "/api/perpetuals/":
        raise ValueError("native API is no longer canonical")
    if expectations["candles"]["resolutions"] != EXPECTED_RESOLUTIONS:
        raise ValueError("candle resolution contract drifted")
    if expectations["candles"]["streamPath"] != "/api/perpetuals/ws/updates":
        raise ValueError("candle stream path drifted")
    if expectations["candles"]["subscriptionType"] != "marketCandles":
        raise ValueError("candle subscription contract drifted")
    if expectations["signing"] != {
        "ambiguousSubmitAction": "reconcile_before_retry",
        "neverSign": "transactionBytes",
        "sign": "signingDigest",
    }:
        raise ValueError("signing contract drifted")
    if expectations["runtimeSafety"]["builtInDeadManSwitch"] is not False:
        raise ValueError("dead-man switch assumption drifted")
    if expectations["writePolicy"] != "deny":
        raise ValueError("read-only write policy drifted")
    if expectations["implementationStatus"] != EXPECTED_IMPLEMENTATION_STATUS:
        raise ValueError("skills implementation-status manifest drifted")
    if skill_provenance["commit"] != EXPECTED_COMMIT:
        raise ValueError("provenance commit drifted")
    if skill_provenance["files"] != EXPECTED_FILES:
        raise ValueError("provenance source files drifted")
    if (
        skill_provenance["file_digest_algorithm"]
        != source["fileDigestAlgorithm"]
    ):
        raise ValueError("provenance digest algorithm drifted")
    if skill_provenance["contract_sha256"] != canonical_sha256(contract):
        raise ValueError("extracted skills contract digest drifted")


def _git(source_dir: Path, *args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(source_dir), *args],
        capture_output=True,
        text=text,
        check=True,
    )
    return result.stdout


def validate_source_checkout(source_dir: Path) -> None:
    """Verify source bytes from an already-fetched checkout; never fetch."""
    remote = _git(source_dir, "remote", "get-url", "origin").strip()
    if remote not in {
        "https://github.com/AftermathFinance/skills",
        "https://github.com/AftermathFinance/skills.git",
        "git@github.com:AftermathFinance/skills.git",
    }:
        raise ValueError(f"unexpected skills source remote: {remote}")
    commit_type = _git(source_dir, "cat-file", "-t", EXPECTED_COMMIT).strip()
    if commit_type != "commit":
        raise ValueError("pinned skills commit is absent from source checkout")
    branch_ref = "refs/remotes/origin/feat/v2-skills"
    branch_check = subprocess.run(
        [
            "git",
            "-C",
            str(source_dir),
            "merge-base",
            "--is-ancestor",
            EXPECTED_COMMIT,
            branch_ref,
        ],
        capture_output=True,
        check=False,
    )
    if branch_check.returncode != 0:
        raise ValueError(
            f"pinned commit does not belong to already-fetched {branch_ref}"
        )
    for relative, expected in EXPECTED_FILES.items():
        raw = _git(
            source_dir,
            "show",
            f"{EXPECTED_COMMIT}:{relative}",
            text=False,
        )
        assert isinstance(raw, bytes)
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise ValueError(f"source digest mismatch for {relative}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="optional already-fetched AftermathFinance/skills checkout",
    )
    args = parser.parse_args()
    validate()
    if args.source_dir is not None:
        validate_source_checkout(args.source_dir.resolve())
    print(
        "skills contract ok: aftermath-perpetuals v3.0.0 "
        f"at {EXPECTED_COMMIT[:12]} ({len(EXPECTED_FILES)} source files"
        f"{'; source bytes verified' if args.source_dir is not None else ''})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
