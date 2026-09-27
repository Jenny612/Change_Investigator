"""Git data collector — all subprocess calls go through here."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from models import CommitInfo, SiblingCommit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(repo_path: str, *args: str, check: bool = True) -> str:
    """Run a git command in *repo_path* and return stdout as a string."""
    result = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={result.returncode}):\n{result.stderr.strip()}"
        )
    return result.stdout


def _extract_pr_number(text: str) -> Optional[str]:
    """Return the first PR number from a commit message, e.g. '(#13824)' → '13824'."""
    m = re.search(r"\(#(\d+)\)", text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_commit_info(repo_path: str, sha: str) -> CommitInfo:
    """Return structured metadata for *sha*."""
    # Use %x00 as field separator to survive newlines in messages
    fmt = "%H%x00%h%x00%s%x00%b%x00%an%x00%ai"
    raw = _git(repo_path, "show", "--no-patch", f"--format={fmt}", sha)
    # The format produces one block; split on null bytes
    parts = raw.split("\x00")
    if len(parts) < 6:
        raise ValueError(f"Unexpected git show output for {sha!r}: {raw[:200]!r}")

    full_sha, short_sha, subject, body, author, date = (p.strip() for p in parts[:6])
    pr_number = _extract_pr_number(subject) or _extract_pr_number(body)

    return CommitInfo(
        sha=full_sha,
        short_sha=short_sha,
        subject=subject,
        body=body,
        author=author,
        date=date,
        pr_number=pr_number,
    )


def get_raw_diff(repo_path: str, sha: str) -> str:
    """Return the full unified diff for *sha* (git show output)."""
    return _git(repo_path, "show", "--no-color", "--diff-algorithm=histogram", sha)


def get_stat(repo_path: str, sha: str) -> str:
    """Return the --stat summary for *sha*."""
    return _git(repo_path, "show", "--stat", "--no-patch", sha)


def get_file_at_parent(repo_path: str, sha: str, file_path: str) -> Optional[str]:
    """Return content of *file_path* at the parent of *sha*, or None if it didn't exist."""
    result = subprocess.run(
        ["git", "-C", repo_path, "show", f"{sha}^:{file_path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def get_file_at_commit(repo_path: str, sha: str, file_path: str) -> Optional[str]:
    """Return content of *file_path* at *sha*, or None if it didn't exist."""
    result = subprocess.run(
        ["git", "-C", repo_path, "show", f"{sha}:{file_path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def get_surrounding_commits(repo_path: str, sha: str, n: int = 10) -> list[CommitInfo]:
    """Return up to *n* commits before and *n* commits after *sha*."""
    commits: list[CommitInfo] = []

    # n commits before (ancestors)
    before_raw = _git(
        repo_path, "log", "--oneline", f"-{n}", f"{sha}~1",
        check=False,
    )
    # n commits after (descendants on the same branch)
    after_raw = _git(
        repo_path, "log", "--oneline", f"-{n}", "--ancestry-path",
        f"{sha}..HEAD",
        check=False,
    )

    for line in (before_raw + "\n" + after_raw).splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2:
            short_sha, subject = parts
            pr_number = _extract_pr_number(subject)
            commits.append(CommitInfo(
                sha=short_sha,
                short_sha=short_sha,
                subject=subject,
                body="",
                author="",
                date="",
                pr_number=pr_number,
            ))

    return commits


def get_changed_files(repo_path: str, sha: str) -> list[tuple[str, str]]:
    """Return list of (status, path) for each file changed in *sha*.

    Status is one of: A (added), M (modified), D (deleted), R (renamed).
    """
    raw = _git(repo_path, "diff-tree", "--no-commit-id", "-r", "--name-status", sha)
    result: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 2:
            status, path = parts
            result.append((status.rstrip("0123456789"), path))
        elif len(parts) == 3:
            # Rename: R<score> old_path new_path
            _, _old, new = parts
            result.append(("R", new))
    return result


def grep_repo(
    repo_path: str,
    pattern: str,
    extra_args: Optional[list[str]] = None,
) -> list[tuple[str, int, str]]:
    """Run git grep for *pattern* and return list of (file, lineno, content)."""
    args = ["grep", "-n", "--no-color", "-I"]
    if extra_args:
        args.extend(extra_args)
    args.append(pattern)

    result = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    matches: list[tuple[str, int, str]] = []
    for line in result.stdout.splitlines():
        # format: file:lineno:content
        parts = line.split(":", 2)
        if len(parts) == 3:
            file_path, lineno_str, content = parts
            try:
                lineno = int(lineno_str)
            except ValueError:
                continue
            matches.append((file_path, lineno, content.strip()))
    return matches


def log_grep(repo_path: str, pattern: str, n: int = 20) -> list[SiblingCommit]:
    """Return commits whose subject matches *pattern* (git log --grep)."""
    raw = _git(
        repo_path, "log", "--oneline", f"-{n}", f"--grep={pattern}",
        check=False,
    )
    result: list[SiblingCommit] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2:
            short_sha, subject = parts
            pr_number = _extract_pr_number(subject)
            result.append(SiblingCommit(sha=short_sha, subject=subject, pr_number=pr_number))
    return result


def list_directory_at_head(repo_path: str, directory: str) -> list[str]:
    """List files in *directory* at HEAD (not at the commit — peers already exist)."""
    raw = _git(repo_path, "ls-files", directory, check=False)
    return [p.strip() for p in raw.splitlines() if p.strip()]
