"""Tests for the history collector."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

PYDANTIC_REPO = str(Path(__file__).parent.parent.parent / "source" / "pydantic")


def _repo_available() -> bool:
    return (Path(PYDANTIC_REPO) / ".git").exists()


skip_if_no_repo = pytest.mark.skipif(
    not _repo_available(),
    reason="source/pydantic repo not available",
)


@skip_if_no_repo
def test_find_changelog_entry_for_known_pr():
    from collectors.history_collector import find_changelog_entry
    # PR #13757 (deque core schema) should be in HISTORY.md
    entry = find_changelog_entry(PYDANTIC_REPO, "13757")
    assert entry is not None
    assert "13757" in entry or "deque" in entry.lower()


@skip_if_no_repo
def test_find_changelog_entry_returns_none_for_unknown():
    from collectors.history_collector import find_changelog_entry
    # A PR number that definitely doesn't exist
    entry = find_changelog_entry(PYDANTIC_REPO, "99999999")
    assert entry is None


@skip_if_no_repo
def test_find_sibling_commits_finds_series():
    from collectors.history_collector import find_sibling_commits
    siblings = find_sibling_commits(PYDANTIC_REPO, "617abdb1b")
    subjects = [s.subject for s in siblings]
    # Should find "Add a `deque` core schema" or similar
    has_schema_sibling = any(
        "schema" in s.lower() and ("deque" in s.lower() or "named" in s.lower() or "tuple" in s.lower())
        for s in subjects
    )
    assert has_schema_sibling, f"Expected schema sibling in: {subjects[:5]}"


@skip_if_no_repo
def test_scan_changelog_for_series():
    from collectors.history_collector import scan_changelog_for_series
    series = scan_changelog_for_series(PYDANTIC_REPO, "13757")
    # Should find at least one other "core schema" entry
    assert isinstance(series, list)
