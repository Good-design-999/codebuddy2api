"""Tool metadata retention and projection boundaries; synthetic requests only."""
import copy
from itertools import product
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import converter
from app.adapters.responses_projection import _project_schema, project_responses_chat_body


def tool_body(agentic=False):
    schema = {
        "type": "object", "title": "Tool inputs", "description": "Read sandbox inputs.",
        "properties": {
            "path": {"type": "string", "description": "Read a sandbox path.", "title": "Path", "enum": ["sandbox", "local"]},
            "list": {"type": "array", "items": {"type": "string", "description": "Item description"}},
            "choice": {"anyOf": [{"type": "string", "description": "Text choice"}, {"type": "integer", "title": "Number"}]},
            "joined": {"allOf": [{"type": "string", "description": "Joined choice"}]},
            "one": {"oneOf": [{"type": "string", "title": "One choice"}]},
            "mapping": {"type": "object", "additionalProperties": {"type": "string", "description": "Map value"}},
            "description": {"type": "string", "title": "A property named description"},
        },
        "required": ["path"], "additionalProperties": False,
    }
    return {
        "messages": [{"role": "system", "content": "You are a coding agent running in the Codex CLI." if agentic else "You are a helpful assistant."},
                     {"role": "user", "content": "Read a file."}],
        "tools": [{"type": "function", "function": {"name": "lookup_data", "description": "Read sandbox data without destructive changes.",
                   "title": "Data reader", "parameters": schema, "strict": True}}],
    }


def metadata(value, path=()):
    result = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("description", "title") and isinstance(item, str):
                result[path + (key,)] = item
            result.update(metadata(item, path + (key,)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.update(metadata(item, path + (index,)))
    return result


class ToolMetadataTests(unittest.TestCase):
    def test_projection_retains_annotations_in_both_modes_without_mutation(self):
        for agentic, keep in product((False, True), repeat=2):
            with self.subTest(agentic=agentic, keep=keep):
                body = tool_body(agentic)
                before = copy.deepcopy(body)
                result, stats = project_responses_chat_body(body, keep_tool_metadata=keep)
                self.assertEqual(stats["mode"], "aggressive" if agentic else "conservative")
                self.assertEqual(metadata(result["tools"]), metadata(body["tools"]) if keep else {})
                function = result["tools"][0]["function"]
                schema = function["parameters"]
                self.assertEqual(function["name"], "lookup_data")
                self.assertIs(function["strict"], True)
                self.assertEqual(schema["required"], ["path"])
                self.assertIs(schema["additionalProperties"], False)
                self.assertEqual(schema["properties"]["path"]["enum"], ["sandbox", "local"])
                self.assertEqual(schema["properties"]["description"]["type"], "string")
                self.assertEqual(body, before)
                if not keep:
                    self.assertEqual(project_responses_chat_body(body), (result, stats))

    def test_retained_metadata_is_desensitized_independently_of_compaction(self):
        body = tool_body(agentic=True)
        before = copy.deepcopy(body)
        for keep, no_compact, force_compact in product((False, True), repeat=3):
            with self.subTest(keep=keep, no_compact=no_compact, force_compact=force_compact), patch.dict(
                    converter.CONFIG, {"desensitize": True, "keep_tool_metadata": keep, "no_compact": no_compact}):
                result = converter._chat_body_desensitize(body, force_compact=force_compact)
                values = metadata(result["tools"])
                if keep:
                    self.assertEqual({key: value.replace("\u200b", "") for key, value in values.items()}, metadata(body["tools"]))
                    self.assertIn("\u200b", result["tools"][0]["function"]["description"])
                else:
                    self.assertEqual(values, {})
                self.assertEqual(result["tools"][0]["function"]["parameters"]["properties"]["path"]["enum"], ["sandbox", "local"])
                self.assertEqual(body, before)
        with patch.dict(converter.CONFIG, {"desensitize": False, "keep_tool_metadata": True}):
            self.assertEqual(converter._chat_body_desensitize(body), before)

    def test_metadata_only_schemas_keep_the_object_fallback(self):
        for schema in ({}, {"description": "Hint"}, {"title": "Node", "$ref": "#/$defs/value"}):
            with self.subTest(schema=schema):
                base = _project_schema(schema)
                retained = _project_schema(schema, keep_tool_metadata=True)
                self.assertEqual(base, {"type": "object"})
                self.assertEqual(retained, {"type": "object", **{key: value for key, value in schema.items() if key in ("description", "title")}})

    def test_retention_does_not_expand_other_schema_projection_rules(self):
        schema = {"type": "string", "description": "Hint", "const": "unchanged legacy projection"}
        self.assertEqual(_project_schema(schema, keep_tool_metadata=True), {"type": "string", "description": "Hint"})
        self.assertEqual(_project_schema(schema, depth=6, keep_tool_metadata=True), {"type": "object"})
        branches = {"oneOf": [schema] * 8}
        result = _project_schema(branches, keep_tool_metadata=True)
        self.assertEqual(len(result["oneOf"]), 6)
        self.assertTrue(all(item == {"type": "string", "description": "Hint"} for item in result["oneOf"]))
        self.assertEqual(len(_project_schema([schema] * 8, keep_tool_metadata=True)), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
