"""Completeness checks for the five initial scanner field matrices."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAPPINGS = ROOT / "aftermath-overlay/field-mappings"
CANDIDATES = {"rooster", "coyote", "gecko", "koala", "terrapin"}
def scanner_syntax(path: Path) -> tuple[set[str], set[str], set[str]]:
    tree = ast.parse(path.read_text())
    calls: set[str] = set()
    dynamic_calls: set[str] = set()
    key_literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                key_literals.add(node.slice.value)
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                key_literals.add(node.args[0].value)
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "call_tool"
                and node.args
            ):
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    calls.add(first.value)
                else:
                    dynamic_calls.add(ast.unparse(first))
    return calls, dynamic_calls, key_literals


def resolved_dynamic_tools(tree: ast.AST, config: dict[str, object]) -> set[str]:
    function = str(config["function"])
    index = int(config["argument_index"])
    resolved: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != function:
            continue
        if len(node.args) <= index:
            raise AssertionError(f"{function} call is missing argument {index}")
        value = node.args[index]
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            raise AssertionError(f"{function} has a non-literal tool argument")
        resolved.add(value.value)
    if not resolved:
        raise AssertionError(f"dynamic dispatcher {function} has no literal call sites")
    return resolved


class FieldMappingTests(unittest.TestCase):
    def test_candidate_set_is_complete(self) -> None:
        files = {path.stem for path in MAPPINGS.glob("*.json")}
        self.assertEqual(CANDIDATES, files)

    def test_sources_tools_and_fields_are_accounted_for(self) -> None:
        for package_id in sorted(CANDIDATES):
            mapping = json.loads((MAPPINGS / f"{package_id}.json").read_text())
            self.assertEqual(package_id, mapping["strategy"])
            consumed = "\n".join(field["consumed"] for field in mapping["fields"])
            self.assertTrue(mapping["fields"])
            tools: set[str] = set()
            dynamic_calls: set[str] = set()
            syntax_keys: set[str] = set()
            for relative in mapping["source_scanners"]:
                path = ROOT / relative
                self.assertTrue(path.is_file(), relative)
                literal, dynamic, keys = scanner_syntax(path)
                tools |= literal
                dynamic_calls |= dynamic
                syntax_keys |= keys
                if dynamic:
                    config = mapping.get("dynamic_tool_dispatch")
                    self.assertIsInstance(
                        config, dict, f"{package_id}: unresolved dynamic call_tool"
                    )
                    tools |= resolved_dynamic_tools(
                        ast.parse(path.read_text()), config
                    )
                    self.assertEqual(
                        {str(config["dispatcher_parameter"])},
                        dynamic,
                        f"{package_id}: dynamic dispatcher expression changed",
                    )
            for tool in tools:
                self.assertIn(tool, consumed, f"{package_id}: missing tool {tool}")
            ignored = {
                key
                for group in mapping.get("ignored_literals", {}).values()
                for key in group["keys"]
            }
            unexplained = {
                key for key in syntax_keys if key not in consumed and key not in ignored
            }
            stale_ignored = ignored - syntax_keys
            self.assertEqual(
                set(), unexplained, f"{package_id}: unexplained scanner key literals"
            )
            self.assertEqual(
                set(), stale_ignored, f"{package_id}: stale ignored key literals"
            )
            for group in mapping.get("ignored_literals", {}).values():
                self.assertTrue(group["reason"].strip())
            statuses = {field["status"] for field in mapping["fields"]}
            self.assertTrue(statuses <= {"mapped", "mapped-transform", "gap", "runtime-local"})
            self.assertIn("gap", statuses)

    def test_every_http_mapping_uses_canonical_api_prefix(self) -> None:
        for path in MAPPINGS.glob("*.json"):
            mapping = json.loads(path.read_text())
            for field in mapping["fields"]:
                target = field["aftermath"]
                if field["status"].startswith("mapped"):
                    self.assertIn("/api/", target, f"{path}: {field['consumed']}")


if __name__ == "__main__":
    unittest.main()
