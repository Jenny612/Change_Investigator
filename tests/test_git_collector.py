"""Tests for the git collector (uses the source/pydantic repo as test fixture)."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

# Path to the pydantic repo (relative to workspace root)
PYDANTIC_REPO = str(Path(__file__).parent.parent.parent / "source" / "pydantic")
TARGET_SHA = "617abdb1b"


def _repo_available() -> bool:
    repo = Path(PYDANTIC_REPO)
    return (repo / ".git").exists()


skip_if_no_repo = pytest.mark.skipif(
    not _repo_available(),
    reason="source/pydantic repo not available",
)


@skip_if_no_repo
def test_get_commit_info_subject():
    from collectors.git_collector import get_commit_info
    info = get_commit_info(PYDANTIC_REPO, TARGET_SHA)
    assert "counter" in info.subject.lower()


@skip_if_no_repo
def test_get_commit_info_pr_number():
    from collectors.git_collector import get_commit_info
    info = get_commit_info(PYDANTIC_REPO, TARGET_SHA)
    assert info.pr_number == "13824"


@skip_if_no_repo
def test_get_commit_info_has_sha():
    from collectors.git_collector import get_commit_info
    info = get_commit_info(PYDANTIC_REPO, TARGET_SHA)
    assert len(info.sha) == 40
    assert info.sha.startswith("617") or TARGET_SHA[:7] in info.sha


@skip_if_no_repo
def test_get_raw_diff_not_empty():
    from collectors.git_collector import get_raw_diff
    raw = get_raw_diff(PYDANTIC_REPO, TARGET_SHA)
    assert len(raw) > 100
    assert "counter" in raw.lower()


@skip_if_no_repo
def test_get_raw_diff_contains_counter_rs():
    from collectors.git_collector import get_raw_diff
    raw = get_raw_diff(PYDANTIC_REPO, TARGET_SHA)
    assert "counter.rs" in raw or "counter" in raw


@skip_if_no_repo
def test_get_surrounding_commits():
    from collectors.git_collector import get_surrounding_commits
    commits = get_surrounding_commits(PYDANTIC_REPO, TARGET_SHA, n=5)
    assert len(commits) > 0


@skip_if_no_repo
def test_get_changed_files_includes_counter():
    from collectors.git_collector import get_changed_files
    files = get_changed_files(PYDANTIC_REPO, TARGET_SHA)
    paths = [p for _, p in files]
    # At least one counter-related file
    assert any("counter" in p.lower() for p in paths), f"No counter file in: {paths[:10]}"


@skip_if_no_repo
def test_grep_repo_finds_counter_schema():
    from collectors.git_collector import grep_repo
    matches = grep_repo(PYDANTIC_REPO, "counter_schema")
    assert len(matches) > 0
    files = [f for f, _, _ in matches]
    assert any("counter" in f or "generate_schema" in f for f in files)


@skip_if_no_repo
def test_log_grep_finds_sibling_commits():
    from collectors.git_collector import log_grep
    siblings = log_grep(PYDANTIC_REPO, "Add a.*core schema", n=20)
    assert len(siblings) >= 1  # at least the target commit or siblings
