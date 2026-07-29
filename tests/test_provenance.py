"""Pinned endpoint and license provenance tests."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProvenanceTests(unittest.TestCase):
    def test_upstream_pin_matches_provenance(self) -> None:
        ref = (ROOT / "UPSTREAM_REF").read_text().strip()
        provenance = json.loads(
            (ROOT / "aftermath-overlay/provenance.json").read_text()
        )
        self.assertRegex(ref, r"^[0-9a-f]{40}$")
        self.assertEqual(ref, provenance["upstream"]["sha"])

    def test_api_provenance_is_exact(self) -> None:
        api = json.loads(
            (ROOT / "aftermath-overlay/provenance.json").read_text()
        )["aftermath_api"]
        self.assertEqual("https://v2-preview.aftermath.finance", api["site"])
        self.assertEqual(
            "https://v2-preview.aftermath.finance/api/openapi/spec.json",
            api["openapi_url"],
        )
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", api["openapi_sha256"]))
        self.assertEqual(251, api["snapshot"]["paths"])
        self.assertEqual(342, api["snapshot"]["schemas"])
        fixture = json.loads(
            (ROOT / "tests/fixtures/openapi-contract-snapshot.json").read_text()
        )
        self.assertEqual(api["openapi_sha256"], fixture["openapi_sha256"])
        self.assertIn("Manual transcription", fixture["verification"])

    def test_shadow_scoring_is_pinned_to_the_upstream_source(self) -> None:
        provenance = json.loads(
            (ROOT / "aftermath-overlay/provenance.json").read_text()
        )
        artifact = provenance["derived_artifacts"]["rooster_shadow_scoring"]
        self.assertEqual(
            artifact["source_upstream_sha"], provenance["upstream"]["sha"]
        )
        source = ROOT / artifact["source"]
        copy = ROOT / artifact["copy"]
        source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        copy_digest = hashlib.sha256(copy.read_bytes()).hexdigest()
        self.assertEqual(source_digest, artifact["sha256"])
        self.assertEqual(copy_digest, artifact["sha256"])

    def test_strategy_discovery_is_exactly_the_pinned_top_level_set(self) -> None:
        upstream = (ROOT / "UPSTREAM_REF").read_text().strip()
        discovered = {
            str(path.relative_to(ROOT))
            for path in (ROOT / "strategies").glob("*/strategy.yaml")
        }
        pinned = {
            path
            for path in subprocess.run(
                [
                    "git",
                    "ls-tree",
                    "-r",
                    "--name-only",
                    upstream,
                    "strategies",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.splitlines()
            if re.fullmatch(r"strategies/[^/]+/strategy\.yaml", path)
        }
        self.assertEqual(len(discovered), 99)
        self.assertEqual(discovered, pinned)


if __name__ == "__main__":
    unittest.main()
