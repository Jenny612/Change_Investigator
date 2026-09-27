"""Tests for the diff parser."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.diff_parser import parse_diff, _classify_file, _detect_language
from models import FileKind


SAMPLE_DIFF = """\
diff --git a/pydantic_core/src/validators/counter.rs b/pydantic_core/src/validators/counter.rs
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/pydantic_core/src/validators/counter.rs
@@ -0,0 +1,10 @@
+use std::sync::Arc;
+use pyo3::prelude::*;
+
+pub struct CounterValidator {
+    strict: bool,
+    name: String,
+}
+
+impl BuildValidator for CounterValidator {
+    const EXPECTED_TYPE: &'static str = "counter";
+}
diff --git a/tests/types/test_counter.py b/tests/types/test_counter.py
new file mode 100644
index 0000000..def5678
--- /dev/null
+++ b/tests/types/test_counter.py
@@ -0,0 +1,5 @@
+from collections import Counter
+import pytest
+
+def test_counter():
+    assert True
diff --git a/pydantic/_internal/_generate_schema.py b/pydantic/_internal/_generate_schema.py
index 111..222 100644
--- a/pydantic/_internal/_generate_schema.py
+++ b/pydantic/_internal/_generate_schema.py
@@ -100,6 +100,7 @@ class GenerateSchema:
     def _dict_schema(self):
         pass
+    def _counter_schema(self, keys_type):
+        return core_schema.counter_schema(self.generate_schema(keys_type))
"""


def test_parse_diff_count():
    diffs = parse_diff(SAMPLE_DIFF)
    assert len(diffs) == 3


def test_parse_diff_new_file_status():
    diffs = parse_diff(SAMPLE_DIFF)
    rs_diff = next(d for d in diffs if d.path.endswith(".rs"))
    assert rs_diff.status == "added"


def test_parse_diff_language_detection():
    diffs = parse_diff(SAMPLE_DIFF)
    rs_diff = next(d for d in diffs if d.path.endswith(".rs"))
    py_diff = next(d for d in diffs if d.path.endswith(".py") and "test" in d.path)
    assert rs_diff.language == "rust"
    assert py_diff.language == "python"


def test_parse_diff_file_kind():
    diffs = parse_diff(SAMPLE_DIFF)
    test_diff = next(d for d in diffs if "test" in d.path)
    src_diff = next(d for d in diffs if d.path.endswith(".rs"))
    modified_diff = next(d for d in diffs if "generate_schema" in d.path)
    assert test_diff.kind == FileKind.TEST
    assert src_diff.kind == FileKind.SOURCE
    assert modified_diff.kind == FileKind.SOURCE


def test_parse_diff_added_lines():
    diffs = parse_diff(SAMPLE_DIFF)
    rs_diff = next(d for d in diffs if d.path.endswith(".rs"))
    assert any("CounterValidator" in line for line in rs_diff.added_lines)
    assert any('"counter"' in line for line in rs_diff.added_lines)


def test_parse_diff_modified_has_added_and_removed():
    diffs = parse_diff(SAMPLE_DIFF)
    mod_diff = next(d for d in diffs if "generate_schema" in d.path)
    assert mod_diff.status == "modified"
    assert any("counter" in line for line in mod_diff.added_lines)


def test_classify_file_test():
    assert _classify_file("tests/types/test_counter.py") == FileKind.TEST
    assert _classify_file("src/validators/test_something.rs") == FileKind.TEST


def test_classify_file_doc():
    assert _classify_file("docs/api/types.md") == FileKind.DOC
    assert _classify_file("HISTORY.md") == FileKind.DOC


def test_classify_file_source():
    assert _classify_file("pydantic/_internal/_generate_schema.py") == FileKind.SOURCE
    assert _classify_file("src/validators/counter.rs") == FileKind.SOURCE


def test_classify_file_config():
    assert _classify_file("pyproject.toml") == FileKind.CONFIG


def test_detect_language():
    assert _detect_language("foo.rs") == "rust"
    assert _detect_language("bar.py") == "python"
    assert _detect_language("README.md") == "markdown"
    assert _detect_language("Makefile") == "other"
