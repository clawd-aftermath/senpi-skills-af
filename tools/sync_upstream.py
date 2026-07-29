#!/usr/bin/env python3
"""Pin an already-fetched upstream commit and regenerate coverage offline.

This script intentionally never fetches. The operator must review/fetch a Senpi
commit separately, then pass its full SHA. That keeps sync deterministic and
lets CI prove generation without network access.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

from coverage_lib import ROOT, build


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ref",
        help="full, already-fetched upstream SHA; updates UPSTREAM_REF",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the pinned ref is the immutable source ancestor",
    )
    args = parser.parse_args()
    pin_path = ROOT / "UPSTREAM_REF"
    ref = args.ref or pin_path.read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        parser.error("--ref/UPSTREAM_REF must be a full lowercase commit SHA")
    git("cat-file", "-e", f"{ref}^{{commit}}")
    if git("merge-base", "HEAD", ref) != ref:
        raise SystemExit(f"pinned upstream {ref} is not an ancestor of HEAD")
    changed_sources = git("diff", "--name-only", ref, "--", "strategies")
    if changed_sources:
        raise SystemExit(
            "strategy source diverges from the pin; create a fresh branch from "
            f"{ref} before generating:\n{changed_sources}"
        )
    outputs = build(ref)
    if args.check:
        extras = {
            path.name
            for path in (ROOT / "aftermath-overlay/catalog").iterdir()
            if path.is_file()
        } - set(outputs)
        if extras:
            raise SystemExit(f"unexpected generated files: {sorted(extras)}")
        for name, content in outputs.items():
            path = ROOT / "aftermath-overlay/catalog" / name
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit(f"stale generated file: {path}")
    else:
        catalog = ROOT / "aftermath-overlay/catalog"
        catalog.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=catalog) as temp_name:
            temporary = Path(temp_name)
            for name, content in outputs.items():
                (temporary / name).write_bytes(content)
            # Publish the complete validated output set, then write the pin last.
            for name in sorted(outputs):
                os.replace(temporary / name, catalog / name)
        for path in catalog.iterdir():
            if path.is_file() and path.name not in outputs:
                path.unlink()
        if args.ref:
            temporary_pin = pin_path.with_suffix(".tmp")
            temporary_pin.write_text(ref + "\n", encoding="utf-8")
            os.replace(temporary_pin, pin_path)
    print(f"upstream pin verified: {ref}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
