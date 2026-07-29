#!/usr/bin/env python3
"""Generate or verify the offline Aftermath coverage catalogs.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import argparse
import sys

from coverage_lib import CATALOG, build


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="fail if generated files are stale"
    )
    args = parser.parse_args()
    outputs = build()
    stale: list[str] = []
    if args.check and CATALOG.exists():
        extras = {
            path.name for path in CATALOG.iterdir() if path.is_file()
        } - set(outputs)
        stale.extend(f"{CATALOG / name} (unexpected)" for name in sorted(extras))
    for name, content in outputs.items():
        path = CATALOG / name
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                stale.append(str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    if not args.check and CATALOG.exists():
        for path in CATALOG.iterdir():
            if path.is_file() and path.name not in outputs:
                path.unlink()
    if stale:
        print("stale generated files:", file=sys.stderr)
        for path in stale:
            print(f"  {path}", file=sys.stderr)
        return 1
    meta = __import__("json").loads(outputs["coverage.json"])["meta"]
    print(
        f"coverage ok: {meta['source_package_count']} packages, "
        f"{meta['instance_count']} instances, "
        f"{meta['enabled_count']} enabled"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
