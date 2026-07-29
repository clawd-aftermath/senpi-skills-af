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
    "skills/api/.api-spec-state.json": "d59f5bee86ef70d003670a19f9dda88c8d1b8a99e7fd97862baed6f65232bd31",
    "skills/api/SKILL.md": "f2d0bcb48b53781a1f7204b38aa92c4cfcce071e67d0bccaf8bede7a5b9f3c38",
    "skills/api/auxiliary-endpoints.md": "6fabb25bc7b0bc7979249015b1d0ea0760261ecc94c92dfde10deacbf61cdbf1",
    "skills/api/ccxt.md": "e0ef2d50de53ca292a8642b320e2611c85c75c12f37e95dc9e6d553fcbdf3f4a",
    "skills/api/dca-and-limit-orders.md": "93dcdb8b9069bdc0212c71ff92c2aaff7320adc9423b4c42e904bb212e97467c",
    "skills/api/error-handling.md": "5cfb48e5aff3d5d2026511413433dd95487ab798876f3e102f350559d93c4e57",
    "skills/api/gotchas.md": "096e4054919de5b893952f73a6d1f9f7bdb45191400cf93919ecfa235b9e8bc1",
    "skills/api/monitoring-patterns.md": "7fd2b8779b57c6edea53aeed3e869458c9efb2831c15385b2195748608cf4323",
    "skills/api/native.md": "732cfecbfbfbb447a5c8c5e8759e0190d7cac5ec258847bbafd68ad9683353ea",
    "skills/api/pools.md": "82290f4272e1d2985630e02d1123b1e1894f2af9f5d2f5705411a73f5d882245",
    "skills/api/prices.md": "8750f0aa48af9f44d68a4a52fcae36db8d389a48486b1be65c49fdae48824cfa",
    "skills/api/safety-and-risk.md": "3b2317266eb84e33f965da09caabdd394b04d3a623ab034bc5f97b5c48759fa5",
    "skills/api/scripts/check_api_changes.py": "f25684111f8374b1b105180b8f6a873f715abc96980c89c7414d6f0616c538ff",
    "skills/api/sdk-reference.md": "0b10ff4df1e432d34a6e59bdaacdf48b501d985c1a5f1ed6d606cdc818e81a8b",
    "skills/api/staking.md": "7ed0d64f310d039b07f92de799e3c898ad3854d49b022fe089516f610f4f67c1",
}
EXPECTED_CLASSIFICATIONS = {
    "skills/api/.api-spec-state.json": "out_of_scope",
    "skills/api/SKILL.md": "applied",
    "skills/api/auxiliary-endpoints.md": "out_of_scope",
    "skills/api/ccxt.md": "applied",
    "skills/api/dca-and-limit-orders.md": "out_of_scope",
    "skills/api/error-handling.md": "applied",
    "skills/api/gotchas.md": "applied",
    "skills/api/monitoring-patterns.md": "applied",
    "skills/api/native.md": "applied",
    "skills/api/pools.md": "out_of_scope",
    "skills/api/prices.md": "out_of_scope",
    "skills/api/safety-and-risk.md": "applied",
    "skills/api/scripts/check_api_changes.py": "out_of_scope",
    "skills/api/sdk-reference.md": "out_of_scope",
    "skills/api/staking.md": "out_of_scope",
}
EXPECTED_REPOSITORY_TOP_LEVEL_DIRECTORIES = ["assets", "skills"]
EXPECTED_SKILL_DIRECTORIES = {
    "skills/api": "classified",
    "skills/gas": "out_of_scope",
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
    "ccxt.pendingOrders": "implemented_read_only",
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


def validate_file_classifications(
    files: dict[str, str], classifications: object
) -> None:
    if not isinstance(classifications, dict):
        raise ValueError("skills/api file classifications are missing")
    if set(classifications) != set(files):
        missing = sorted(set(files) - set(classifications))
        extra = sorted(set(classifications) - set(files))
        raise ValueError(
            f"skills/api classification coverage drifted: missing={missing} extra={extra}"
        )
    observed = {
        path: entry.get("status") if isinstance(entry, dict) else None
        for path, entry in classifications.items()
    }
    if observed != EXPECTED_CLASSIFICATIONS:
        raise ValueError("skills/api file classifications drifted")
    for path, entry in classifications.items():
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"skills/api classification reason missing for {path}")


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
    validate_file_classifications(
        EXPECTED_FILES, source.get("fileClassifications")
    )
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
    if expectations["ccxtPendingOrders"] != {
        "accountField": "accountNumber",
        "marketField": "chId",
        "path": "/api/ccxt/myPendingOrders",
        "writeAccountField": "accountId",
        "writeAccountMeaning": "capability_object_id",
        "writePolicy": "deny",
    }:
        raise ValueError("CCXT pending-orders contract drifted")
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
    if skill_provenance["file_classifications"] != EXPECTED_CLASSIFICATIONS:
        raise ValueError("provenance file classifications drifted")
    if (
        source["repositoryTopLevelDirectories"]
        != EXPECTED_REPOSITORY_TOP_LEVEL_DIRECTORIES
    ):
        raise ValueError("skills repository top-level directory contract drifted")
    observed_skill_directories = {
        path: entry.get("status") if isinstance(entry, dict) else None
        for path, entry in source["skillDirectories"].items()
    }
    if observed_skill_directories != EXPECTED_SKILL_DIRECTORIES:
        raise ValueError("skills directory scope contract drifted")
    if any(
        not isinstance(entry.get("reason"), str) or not entry["reason"].strip()
        for entry in source["skillDirectories"].values()
    ):
        raise ValueError("skills directory scope reason missing")
    if (
        skill_provenance["repository_top_level_directories"]
        != EXPECTED_REPOSITORY_TOP_LEVEL_DIRECTORIES
    ):
        raise ValueError("provenance repository directory scope drifted")
    if skill_provenance["skill_directories"] != EXPECTED_SKILL_DIRECTORIES:
        raise ValueError("provenance skill directory scope drifted")
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


def validate_source_checkout(source_dir: Path) -> str:
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
    branch_tip = _git(source_dir, "rev-parse", branch_ref).strip()
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
    top_level_directories = sorted(
        str(
            _git(
                source_dir,
                "ls-tree",
                "-d",
                "--name-only",
                EXPECTED_COMMIT,
            )
        ).splitlines()
    )
    if top_level_directories != EXPECTED_REPOSITORY_TOP_LEVEL_DIRECTORIES:
        raise ValueError(
            "skills repository top-level directory scope drifted: "
            f"observed={top_level_directories}"
        )
    skill_directories = {
        f"skills/{name}"
        for name in str(
            _git(
                source_dir,
                "ls-tree",
                "-d",
                "--name-only",
                f"{EXPECTED_COMMIT}:skills",
            )
        ).splitlines()
    }
    if skill_directories != set(EXPECTED_SKILL_DIRECTORIES):
        raise ValueError(
            "skills directory scope incomplete: "
            f"observed={sorted(skill_directories)}"
        )
    tree_output = _git(
        source_dir,
        "ls-tree",
        "-r",
        "--name-only",
        EXPECTED_COMMIT,
        "skills/api",
    )
    tree_paths = set(str(tree_output).splitlines())
    if tree_paths != set(EXPECTED_FILES):
        missing = sorted(tree_paths - set(EXPECTED_FILES))
        stale = sorted(set(EXPECTED_FILES) - tree_paths)
        raise ValueError(
            f"skills/api tree manifest incomplete: unclassified={missing} absent={stale}"
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
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    ccxt_contract = contract["expectations"]["ccxtPendingOrders"]
    source_bound_fields = {
        key: ccxt_contract.get(key)
        for key in ("path", "marketField", "accountField", "writeAccountField")
    }
    if any(
        not isinstance(value, str) or not value
        for value in source_bound_fields.values()
    ):
        raise ValueError("CCXT source-bound contract fields must be non-empty strings")
    ccxt_source = _git(
        source_dir,
        "show",
        f"{EXPECTED_COMMIT}:skills/api/ccxt.md",
    )
    source_snippets = (
        f"POST {source_bound_fields['path']}",
        f"| `{source_bound_fields['marketField']}` | Market object ID |",
        (
            f"| `{source_bound_fields['writeAccountField']}` | "
            "Account capability object ID (for writes) |"
        ),
        (
            f"| `{source_bound_fields['accountField']}` | "
            "Numeric account identifier (for reads/streams) |"
        ),
    )
    for snippet in source_snippets:
        if snippet not in ccxt_source:
            raise ValueError(
                f"CCXT extracted contract is not bound to source snippet: {snippet}"
            )
    return str(branch_tip)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="optional already-fetched AftermathFinance/skills checkout",
    )
    args = parser.parse_args()
    validate()
    branch_tip = None
    if args.source_dir is not None:
        branch_tip = validate_source_checkout(args.source_dir.resolve())
    print(
        "skills contract ok: aftermath-perpetuals v3.0.0 "
        f"at {EXPECTED_COMMIT[:12]} ({len(EXPECTED_FILES)} source files"
        f"{'; source bytes verified' if args.source_dir is not None else ''})"
    )
    if branch_tip is not None:
        print(
            "source verifier never fetches; operator must fetch origin "
            f"feat/v2-skills immediately before verification; observed tip={branch_tip}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
