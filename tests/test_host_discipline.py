"""The retired preview host must not appear in active repository content.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

The launched production host is the bare Aftermath domain.  The old preview
deployment still answers but exposes a stale market set, so allowing it as a
runtime or documentation default is dangerous.

The host token is assembled from pieces at runtime so this file does not itself
contain a usable retired URL, which would make the check flag its own guard.
Locked historical provenance is exempted explicitly and tested separately.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDORED = ROOT / "AFTERMATH_SKILLS_REF"

_PRODUCTION_HOST = "aftermath" + "." + "finance"
_RETIRED_PREVIEW_PREFIX = "v2-" + "preview."

# Any scheme, any subdomain, followed by the bare host.
_HOST_RE = re.compile(
    r"(?:https?|wss?)://([A-Za-z0-9.-]*)" + re.escape(_PRODUCTION_HOST)
)

SEARCHED_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".ts",
    ".js",
    ".txt",
    ".toml",
    ".cfg",
    ".sh",
    ".example",
}

SKIPPED_DIRECTORIES = {
    ".git",
    "__pycache__",
    "AFTERMATH_SKILLS_REF",
}

SKIPPED_FILES = {
    # Observation-dated, hash-locked evidence with no repository regeneration
    # path. It is not runtime configuration or current endpoint documentation.
    Path("aftermath-overlay/provenance.json"),
}


def searched_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        parts = set(relative.parts)
        if parts & SKIPPED_DIRECTORIES:
            continue
        if relative in SKIPPED_FILES:
            continue
        if path.suffix not in SEARCHED_SUFFIXES and path.name != ".env.example":
            continue
        files.append(path)
    return files


def offending_lines(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover
        return []
    hits: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _HOST_RE.finditer(line):
            if match.group(1) == _RETIRED_PREVIEW_PREFIX:
                hits.append((number, line.strip()))
    return hits


class HostDisciplineTests(unittest.TestCase):
    def test_no_active_file_references_the_retired_preview_host(self):
        offenders: list[str] = []
        for path in searched_files():
            for number, line in offending_lines(path):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line[:120]}")
        self.assertEqual(
            offenders,
            [],
            "the retired preview API host must not appear in active content; "
            "the production host is https://" + _PRODUCTION_HOST,
        )

    def test_locked_historical_carve_outs_are_explicit(self):
        retired_host = _RETIRED_PREVIEW_PREFIX + _PRODUCTION_HOST
        delta = (VENDORED / "README-DELTA.md").read_text(encoding="utf-8")
        self.assertIn("retired host", delta)
        self.assertIn(retired_host, delta)
        provenance = (
            ROOT / "aftermath-overlay" / "provenance.json"
        ).read_text(encoding="utf-8")
        self.assertIn(retired_host, provenance)

    def test_vendored_skills_name_the_launched_production_host(self):
        production_urls = 0
        for path in (VENDORED / "skills").rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                production_urls += text.count("https://" + _PRODUCTION_HOST)
                production_urls += text.count("wss://" + _PRODUCTION_HOST)
        self.assertGreater(production_urls, 0)

    def test_the_host_is_defined_exactly_once_in_the_runtime(self):
        """One assignment, everywhere else reads it.

        Prose may mention the host (the modules explain the trap); exactly one
        line may *assign* it.
        """
        assignment = re.compile(
            r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*[:=].*['\"](?:https?|wss?)://"
            + re.escape(_PRODUCTION_HOST)
        )
        definitions: list[str] = []
        for path in sorted((ROOT / "aftermath_runtime").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), start=1):
                if assignment.match(line):
                    definitions.append(
                        f"{path.relative_to(ROOT)}:{number}: {line.strip()}"
                    )
        self.assertEqual(
            len(definitions),
            1,
            "the API host must be assigned exactly once; every other call site "
            f"reads DEFAULT_API_BASE_URL / AF_API_BASE_URL. Found: {definitions}",
        )
        self.assertTrue(
            definitions[0].startswith("aftermath_runtime/config.py:"), definitions
        )
        self.assertIn("DEFAULT_API_BASE_URL =", definitions[0])

    def test_no_other_module_hardcodes_the_host_in_a_default_argument(self):
        from aftermath_runtime.transport import (
            UrllibAdapterTransport,
            UrllibReadTransport,
        )
        from aftermath_runtime.config import DEFAULT_API_BASE_URL

        for cls in (UrllibReadTransport, UrllibAdapterTransport):
            with self.subTest(cls=cls.__name__):
                self.assertIs(
                    cls.__dataclass_fields__["base_url"].default,
                    DEFAULT_API_BASE_URL,
                )


def executable_source(path: Path) -> str:
    """The file's code with comments and string literals removed.

    Naming the retired venue in a docstring is not merely allowed, it is the
    point: the modules explain what was replaced and why.  What must not exist
    is venue machinery — a host, an SDK import, an env var, a field name that
    only means something on that venue.  Stripping comments and strings is what
    separates "documents the removal" from "still does it".
    """
    import io
    import tokenize

    kept: list[str] = []
    with path.open("rb") as handle:
        try:
            for token in tokenize.tokenize(handle.readline):
                if token.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL):
                    continue
                kept.append(token.string)
        except (tokenize.TokenError, IndentationError):  # pragma: no cover
            return io.StringIO(path.read_text(encoding="utf-8")).read()
    return "\n".join(kept)


class VenueRemovalTests(unittest.TestCase):
    """No upstream venue may survive in an Aftermath EXECUTION path."""

    RUNTIME_DIRS = ("aftermath_runtime",)

    # Venue machinery, as opposed to prose about it.
    VENUE_HOSTS = ("hyperliquid" + ".xyz", "api.hyperliquid", "api.hl")
    VENUE_IMPORTS = ("import hyperliquid", "from hyperliquid", "import hl_")
    VENUE_IDENTIFIERS = (
        "sendAsset",
        "destinationDex",
        "dex_index",
        "meta_index",
        "marginPct",
        "margin_pct",
        "HL_API",
        "HL_SECRET",
        "HL_WALLET",
    )

    def runtime_files(self) -> list[Path]:
        return [
            path
            for directory in self.RUNTIME_DIRS
            for path in (ROOT / directory).rglob("*.py")
        ]

    def test_no_venue_host_appears_anywhere_in_the_runtime(self):
        offenders: list[str] = []
        for path in self.runtime_files():
            text = path.read_text(encoding="utf-8").lower()
            for host in self.VENUE_HOSTS:
                if host.lower() in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {host}")
        self.assertEqual(offenders, [])

    def test_no_venue_sdk_is_imported(self):
        offenders: list[str] = []
        for path in self.runtime_files():
            text = path.read_text(encoding="utf-8").lower()
            for token in self.VENUE_IMPORTS:
                if token.lower() in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {token}")
        self.assertEqual(offenders, [])

    def test_no_venue_identifier_survives_in_executable_code(self):
        """Docstrings may name them; code may not use them."""
        offenders: list[str] = []
        for path in self.runtime_files():
            source = executable_source(path)
            for token in self.VENUE_IDENTIFIERS:
                if token in source:
                    offenders.append(f"{path.relative_to(ROOT)}: {token}")
        self.assertEqual(offenders, [])

    def test_the_runtime_documents_that_market_ids_are_resolved_not_built(self):
        text = " ".join(
            (ROOT / "aftermath_runtime" / "ids.py")
            .read_text(encoding="utf-8")
            .split()
        )
        self.assertIn("Never construct one from a symbol", text)

    def test_hip3_prefixes_are_stripped_rather_than_carried(self):
        from aftermath_runtime.ids import normalise_instrument

        self.assertEqual(normalise_instrument("xyz:GOLD"), "GOLD")

    def test_venue_leakage_into_a_request_body_fails_closed(self):
        from aftermath_runtime.execution import assert_no_venue_leakage

        with self.assertRaises(Exception):
            assert_no_venue_leakage({"marginPct": 20})
        with self.assertRaises(Exception):
            assert_no_venue_leakage({"marketId": "xyz:GOLD"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
