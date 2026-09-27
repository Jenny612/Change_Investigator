"""Diff parser — turns a raw unified diff string into structured FileDiff objects."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from models import FileDiff, FileKind


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".rs": "rust",
    ".md": "markdown",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".txt": "text",
    ".sh": "shell",
    ".ts": "typescript",
    ".js": "javascript",
}

_TEST_PATTERNS = [
    "/tests/",
    "/test_",
    "_test.py",
    "_spec.rs",
    "/benches/",
]

_DOC_PATTERNS = [
    "/docs/",
    ".md",
    "HISTORY",
    "CHANGELOG",
    "README",
]

_CONFIG_PATTERNS = [
    "pyproject.toml",
    "Cargo.toml",
    "Cargo.lock",
    ".yaml",
    ".yml",
    ".cfg",
    ".ini",
    "requirements",
    "uv.lock",
    ".gitignore",
    "Makefile",
]


def _classify_file(path: str) -> FileKind:
    p = path.lower()
    if any(pat in p for pat in _TEST_PATTERNS):
        return FileKind.TEST
    if any(pat in p for pat in _DOC_PATTERNS):
        return FileKind.DOC
    if any(pat in p for pat in _CONFIG_PATTERNS):
        return FileKind.CONFIG
    ext = Path(path).suffix.lower()
    if ext in (".py", ".rs", ".c", ".cpp", ".h", ".go", ".ts", ".js"):
        return FileKind.SOURCE
    return FileKind.OTHER


def _detect_language(path: str) -> str:
    return _LANGUAGE_MAP.get(Path(path).suffix.lower(), "other")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Pattern: diff --git a/path b/path
_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_NEW_FILE_RE = re.compile(r"^new file mode")
_DELETED_FILE_RE = re.compile(r"^deleted file mode")
_RENAME_FROM_RE = re.compile(r"^rename from (.+)$")
_RENAME_TO_RE = re.compile(r"^rename to (.+)$")
_INDEX_RE = re.compile(r"^index ")
_HUNK_RE = re.compile(r"^@@ ")


def parse_diff(raw_diff: str) -> list[FileDiff]:
    """Parse a unified diff string into a list of FileDiff objects."""
    # Split into per-file sections on "diff --git" boundaries
    file_sections: list[str] = []
    current: list[str] = []

    for line in raw_diff.splitlines(keepends=True):
        if line.startswith("diff --git ") and current:
            file_sections.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        file_sections.append("".join(current))

    diffs: list[FileDiff] = []
    for section in file_sections:
        diff = _parse_file_section(section)
        if diff is not None:
            diffs.append(diff)
    return diffs


def _parse_file_section(section: str) -> Optional[FileDiff]:
    lines = section.splitlines()
    if not lines:
        return None

    # First line: diff --git a/X b/Y
    m = _DIFF_HEADER_RE.match(lines[0])
    if not m:
        return None

    a_path = m.group(1)
    b_path = m.group(2)

    status = "modified"
    old_path: Optional[str] = None

    added_lines: list[str] = []
    removed_lines: list[str] = []

    for line in lines[1:]:
        if _NEW_FILE_RE.match(line):
            status = "added"
        elif _DELETED_FILE_RE.match(line):
            status = "deleted"
        elif rm := _RENAME_FROM_RE.match(line):
            old_path = rm.group(1)
            status = "renamed"
        elif _RENAME_TO_RE.match(line):
            pass  # b_path already captures destination
        elif line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed_lines.append(line[1:])

    path = b_path if status != "deleted" else a_path

    return FileDiff(
        path=path,
        old_path=old_path,
        status=status,
        kind=_classify_file(path),
        language=_detect_language(path),
        raw_diff=section,
        added_lines=added_lines,
        removed_lines=removed_lines,
        # before/after content is filled in later by source_collector
    )


def added_lines_text(diff: FileDiff) -> str:
    return "\n".join(diff.added_lines)


def removed_lines_text(diff: FileDiff) -> str:
    return "\n".join(diff.removed_lines)
