"""Pinned endpoint and license provenance tests."""

from __future__ import annotations

import json
import re
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


if __name__ == "__main__":
    unittest.main()
