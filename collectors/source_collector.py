"""Source collector — reads files from the repo and runs git grep."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from models import FileDiff, FileKind, GrepMatch
from collectors.git_collector import grep_repo, list_directory_at_head


MAX_FILE_LINES = 250   # truncate very large files for context building
MAX_GREP_RESULTS_PER_SYMBOL = 30


def read_file_at_head(repo_path: str, file_path: str) -> Optional[str]:
    """Read *file_path* from the working tree (HEAD) of *repo_path*.

    Returns None if the file does not exist.
    """
    full = Path(repo_path) / file_path
    if not full.exists():
        return None
    try:
        return full.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return None


def read_new_files(repo_path: str, diffs: list[FileDiff]) -> dict[str, str]:
    """Read full content of files that were *added* in this commit.

    Returns a dict of path → content (truncated to MAX_FILE_LINES).
    """
    result: dict[str, str] = {}
    for diff in diffs:
        if diff.status == "added" and diff.kind in (FileKind.SOURCE, FileKind.TEST):
            content = read_file_at_head(repo_path, diff.path)
            if content is not None:
                result[diff.path] = _truncate(content, MAX_FILE_LINES)
    return result


def read_modified_files(repo_path: str, diffs: list[FileDiff]) -> dict[str, str]:
    """Read current content of *modified* source files (after the commit)."""
    result: dict[str, str] = {}
    for diff in diffs:
        if diff.status == "modified" and diff.kind == FileKind.SOURCE:
            content = read_file_at_head(repo_path, diff.path)
            if content is not None:
                result[diff.path] = _truncate(content, MAX_FILE_LINES)
    return result


def read_test_files(repo_path: str, diffs: list[FileDiff]) -> dict[str, str]:
    """Read full content of test files touched by the commit."""
    result: dict[str, str] = {}
    for diff in diffs:
        if diff.kind == FileKind.TEST:
            content = read_file_at_head(repo_path, diff.path)
            if content is not None:
                result[diff.path] = content  # test files kept in full
    return result


def read_doc_additions(diffs: list[FileDiff], max_lines: int = 60) -> dict[str, str]:
    """Return added lines from doc files (not full content — just the additions)."""
    result: dict[str, str] = {}
    for diff in diffs:
        if diff.kind == FileKind.DOC and diff.added_lines:
            added = "\n".join(diff.added_lines[:max_lines])
            result[diff.path] = added
    return result


def grep_for_symbols(
    repo_path: str,
    symbols: list[str],
    max_symbols: int = 12,
) -> dict[str, list[GrepMatch]]:
    """Run git grep for each symbol; return a dict of symbol → list of GrepMatch."""
    result: dict[str, list[GrepMatch]] = {}

    for symbol in symbols[:max_symbols]:
        matches_raw = grep_repo(repo_path, re.escape(symbol) if _needs_escape(symbol) else symbol)
        matches: list[GrepMatch] = []
        for file_path, lineno, content in matches_raw[:MAX_GREP_RESULTS_PER_SYMBOL]:
            matches.append(GrepMatch(
                file_path=file_path,
                line_number=lineno,
                line_content=content,
                symbol=symbol,
            ))
        if matches:
            result[symbol] = matches

    return result


def _needs_escape(symbol: str) -> bool:
    return bool(re.search(r"[.*+?^${}()|[\]\\]", symbol))


def _truncate(content: str, max_lines: int) -> str:
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content
    return "\n".join(lines[:max_lines]) + f"\n... [truncated at {max_lines} lines]"


def get_excerpt(content: str, max_lines: int = 40) -> str:
    """Return the first *max_lines* lines of *content*."""
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content
    return "\n".join(lines[:max_lines]) + f"\n... [{len(lines) - max_lines} more lines]"
