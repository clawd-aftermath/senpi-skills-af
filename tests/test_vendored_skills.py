"""The vendored skills must be byte-identical to the pinned upstream commit.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

`AFTERMATH_SKILLS_REF/` is a reference, not a source. A silent edit to a
vendored file would turn the next upstream sync from a diff into an
archaeology exercise, and would quietly break the conformance claims that cite
these files. The per-file SHA-256 digests are already pinned in
`contracts/aftermath-skills-v3-contract.json`; this checks the bytes on disk
against them.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDORED = ROOT / "AFTERMATH_SKILLS_REF"
CONTRACT = ROOT / "contracts" / "aftermath-skills-v3-contract.json"
EXPECTED_COMMIT = "5b614db62dcd2e58f442e93661f608fe7b073c32"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VendoredSkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.files = self.contract["source"]["files"]

    def test_the_pin_file_records_the_upstream_commit(self):
        self.assertEqual(
            (VENDORED / "COMMIT").read_text(encoding="utf-8").strip(),
            EXPECTED_COMMIT,
        )

    def test_every_pinned_file_is_present_and_byte_identical(self):
        mismatched: list[str] = []
        for relative, expected in sorted(self.files.items()):
            path = VENDORED / relative
            if not path.is_file():
                mismatched.append(f"{relative}: MISSING")
                continue
            actual = digest(path)
            if actual != expected:
                mismatched.append(f"{relative}: {actual} != {expected}")
        self.assertEqual(
            mismatched,
            [],
            "vendored skill files were edited; they must stay byte-identical to "
            f"AftermathFinance/skills@{EXPECTED_COMMIT[:12]}",
        )

    def test_no_unpinned_file_was_added_under_skills_api(self):
        present = {
            str(path.relative_to(VENDORED))
            for path in (VENDORED / "skills" / "api").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        self.assertEqual(present, set(self.files))

    def test_the_delta_and_pin_documents_exist_and_name_the_commit(self):
        for name in ("PINNED.md", "README-DELTA.md"):
            with self.subTest(document=name):
                path = VENDORED / name
                self.assertTrue(path.is_file(), f"{name} is missing")
        self.assertIn(EXPECTED_COMMIT, (VENDORED / "PINNED.md").read_text())

    def test_the_delta_document_records_the_retired_host_discrepancy(self):
        text = (VENDORED / "README-DELTA.md").read_text(encoding="utf-8")
        for phrase in (
            "22 places",
            "v2-preview",
            "servers",
            "production mainnet",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_the_upstream_licence_travelled_with_the_files(self):
        self.assertIn("Apache License", (VENDORED / "LICENSE").read_text())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
