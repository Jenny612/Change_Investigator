"""History collector — searches CHANGELOG/HISTORY files for PR references and
finds sibling commits that follow the same naming pattern."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from models import SiblingCommit
from collectors.git_collector import log_grep


_CHANGELOG_NAMES = [
    "HISTORY.md",
    "CHANGELOG.md",
    "CHANGES.md",
    "CHANGELOG.rst",
    "CHANGES.rst",
    "HISTORY.rst",
    "CHANGELOG",
    "CHANGES",
]

_CONTEXT_LINES = 8   # lines of context around the PR mention


def find_changelog_file(repo_path: str) -> Optional[Path]:
    """Return the first changelog-like file found in *repo_path*."""
    root = Path(repo_path)
    for name in _CHANGELOG_NAMES:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def find_changelog_entry(repo_path: str, pr_number: str) -> Optional[str]:
    """Search HISTORY/CHANGELOG for a reference to *pr_number*.

    Returns a few lines of context around the first match, or None.
    """
    changelog = find_changelog_file(repo_path)
    if changelog is None:
        return None

    try:
        lines = changelog.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    pattern = re.compile(rf"#\s*{re.escape(pr_number)}\b")
    for i, line in enumerate(lines):
        if pattern.search(line):
            start = max(0, i - _CONTEXT_LINES)
            end = min(len(lines), i + _CONTEXT_LINES + 1)
            snippet = "\n".join(lines[start:end])
            return f"[{changelog.name}:{i+1}]\n{snippet}"

    return None


def find_sibling_commits(
    repo_path: str,
    sha: str,
    title_prefix: Optional[str] = None,
    n: int = 30,
) -> list[SiblingCommit]:
    """Return commits with subjects matching patterns related to the current commit.

    Tries several heuristic patterns:
    1. Caller-supplied *title_prefix*
    2. "Add a `.*` core schema" (pydantic-core series)
    3. "Add.*schema" (generic)
    """
    patterns = []
    if title_prefix:
        patterns.append(title_prefix)
    # Always try known series patterns
    patterns.extend([
        "Add a.*core schema",
        "Add.*core schema",
    ])

    seen: set[str] = set()
    result: list[SiblingCommit] = []

    for pattern in patterns:
        for commit in log_grep(repo_path, pattern, n=n):
            if commit.sha not in seen and not commit.sha.startswith(sha[:7]):
                seen.add(commit.sha)
                result.append(commit)

    return result


def scan_changelog_for_series(repo_path: str, pr_number: str) -> list[str]:
    """Find all changelog lines that reference a pattern similar to the target PR entry.

    For example, if PR #13824 is "Add a `counter` core schema", find other
    "Add a ... core schema" lines in the changelog.
    """
    changelog = find_changelog_file(repo_path)
    if changelog is None:
        return []

    try:
        text = changelog.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    # Find what the current PR's line looks like, then search for siblings
    target_pattern = re.compile(rf"#\s*{re.escape(pr_number)}\b")
    series_pattern = re.compile(r"Add a? [`\w].*(?:core schema|schema type)", re.IGNORECASE)

    lines = text.splitlines()
    results: list[str] = []

    target_line = ""
    for line in lines:
        if target_pattern.search(line):
            target_line = line
            break

    for line in lines:
        if series_pattern.search(line) and line != target_line:
            results.append(line.strip())

    return results[:10]
