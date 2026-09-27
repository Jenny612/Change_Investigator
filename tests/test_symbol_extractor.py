"""Tests for the symbol extractor."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.symbol_extractor import extract_new_symbols, prioritise_symbols
from analysis.diff_parser import parse_diff
from models import FileDiff, FileKind


def _make_rust_diff(added_lines: list[str]) -> FileDiff:
    return FileDiff(
        path="src/validators/counter.rs",
        old_path=None,
        status="added",
        kind=FileKind.SOURCE,
        language="rust",
        raw_diff="",
        added_lines=added_lines,
    )


def _make_python_diff(added_lines: list[str]) -> FileDiff:
    return FileDiff(
        path="pydantic/_internal/_generate_schema.py",
        old_path=None,
        status="modified",
        kind=FileKind.SOURCE,
        language="python",
        raw_diff="",
        added_lines=added_lines,
    )


def test_extract_rust_struct_name():
    diff = _make_rust_diff(["pub struct CounterValidator {"])
    symbols = extract_new_symbols([diff])
    assert "CounterValidator" in symbols


def test_extract_rust_expected_type():
    diff = _make_rust_diff(['    const EXPECTED_TYPE: &\'static str = "counter";'])
    symbols = extract_new_symbols([diff])
    assert "counter" in symbols


def test_extract_python_class():
    diff = _make_python_diff(["class CounterSchema(TypedDict, total=False):"])
    symbols = extract_new_symbols([diff])
    assert "CounterSchema" in symbols


def test_extract_python_def():
    diff = _make_python_diff(["def counter_schema("])
    symbols = extract_new_symbols([diff])
    assert "counter_schema" in symbols


def test_no_duplicates():
    diff = _make_rust_diff([
        "pub struct CounterValidator {",
        "pub struct CounterValidator {",  # duplicate
    ])
    symbols = extract_new_symbols([diff])
    assert symbols.count("CounterValidator") == 1


def test_skip_common_noise_words():
    diff = _make_python_diff([
        "def self():",
        "class None:",
        "def true():",
    ])
    symbols = extract_new_symbols([diff])
    # 'self', 'None', 'true' should be filtered
    assert "self" not in symbols
    assert "None" not in symbols
    assert "true" not in symbols


def test_prioritise_camel_case_first():
    symbols = ["counter", "CounterValidator", "ordered_dict", "OrderedDictValidator"]
    prioritised = prioritise_symbols(symbols)
    # CamelCase should come first
    assert prioritised.index("CounterValidator") < prioritised.index("counter")
    assert prioritised.index("OrderedDictValidator") < prioritised.index("ordered_dict")


def test_extract_from_real_rust_snippet():
    lines = [
        "use std::sync::Arc;",
        "pub struct CounterValidator {",
        "    strict: bool,",
        "}",
        "impl BuildValidator for CounterValidator {",
        '    const EXPECTED_TYPE: &\'static str = "counter";',
        "}",
    ]
    diff = _make_rust_diff(lines)
    symbols = extract_new_symbols([diff])
    assert "CounterValidator" in symbols
    assert "counter" in symbols
