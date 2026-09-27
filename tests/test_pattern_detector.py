"""Tests for pattern detector."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from analysis.pattern_detector import reconstruct_before_state, extract_test_assertions
from models import FileDiff, FileKind

PYDANTIC_REPO = str(Path(__file__).parent.parent.parent / "source" / "pydantic")


def _repo_available() -> bool:
    return (Path(PYDANTIC_REPO) / ".git").exists()


skip_if_no_repo = pytest.mark.skipif(
    not _repo_available(),
    reason="source/pydantic repo not available",
)


def _make_added_diff(path: str) -> FileDiff:
    return FileDiff(
        path=path,
        old_path=None,
        status="added",
        kind=FileKind.SOURCE,
        language="rust",
        raw_diff="",
        added_lines=["pub struct CounterValidator {}"],
    )


def _make_modified_diff(path: str, removed: list[str]) -> FileDiff:
    return FileDiff(
        path=path,
        old_path=None,
        status="modified",
        kind=FileKind.SOURCE,
        language="python",
        raw_diff="",
        added_lines=["def _counter_schema(self):"],
        removed_lines=removed,
    )


def test_reconstruct_before_new_file():
    diff = _make_added_diff("src/validators/counter.rs")
    items = reconstruct_before_state([diff])
    assert len(items) == 1
    assert "new in this commit" in items[0].content.lower() or "did not exist" in items[0].content.lower()
    assert items[0].source_file == "src/validators/counter.rs"


def test_reconstruct_before_modified_file():
    diff = _make_modified_diff(
        "pydantic/_generate_schema.py",
        ["    # old counter implementation", "    pass"],
    )
    items = reconstruct_before_state([diff])
    assert len(items) == 1
    assert "old counter" in items[0].content


def test_reconstruct_before_no_evidence_for_doc():
    doc_diff = FileDiff(
        path="docs/counter.md",
        old_path=None,
        status="added",
        kind=FileKind.DOC,
        language="markdown",
        raw_diff="",
        added_lines=["# Counter documentation"],
    )
    items = reconstruct_before_state([doc_diff])
    # Doc files don't produce before-state evidence
    assert len(items) == 0


def test_extract_test_assertions_finds_comments():
    contents = {
        "tests/test_counter.py": (
            "# zero and negative counts are kept as is\n"
            "def test_counter_values_preserved():\n"
            "    ta = TypeAdapter(Counter[str])\n"
            "    assert dict(v) == {'a': 3, 'b': 0, 'c': -2}\n"
        )
    }
    items = extract_test_assertions(contents)
    comment_items = [e for e in items if e.content.startswith("#")]
    assert len(comment_items) >= 1
    assert any("negative" in e.content or "zero" in e.content for e in comment_items)


def test_extract_test_assertions_finds_asserts():
    contents = {
        "tests/test_counter.py": (
            "def test_counter():\n"
            "    assert isinstance(v, Counter)\n"
            "    assert v == Counter({'a': 1})\n"
        )
    }
    items = extract_test_assertions(contents)
    assert_items = [e for e in items if e.content.startswith("assert")]
    assert len(assert_items) >= 1


@skip_if_no_repo
def test_find_peer_files_for_counter():
    from analysis.pattern_detector import find_peer_files
    from analysis.diff_parser import parse_diff
    from collectors.git_collector import get_raw_diff

    raw_diff = get_raw_diff(PYDANTIC_REPO, "617abdb1b")
    diffs = parse_diff(raw_diff)
    peers = find_peer_files(PYDANTIC_REPO, diffs)

    peer_paths = [p.path for p in peers]
    # Should find ordered_dict.rs or deque.rs as peers in the same validators directory
    has_peer = any(
        "ordered_dict" in p or "deque" in p or "dict" in p
        for p in peer_paths
    )
    assert has_peer, f"Expected dict/ordered_dict peer in: {peer_paths}"
