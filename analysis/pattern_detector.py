"""Pattern detector — finds structural peers and reconstructs the before-state."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from models import FileDiff, FileKind, PeerFile, EvidenceItem, ClaimKind
from collectors.git_collector import list_directory_at_head
from collectors.source_collector import read_file_at_head, get_excerpt


MAX_PEER_FILES = 5
MAX_PEER_LINES = 40


def find_peer_files(repo_path: str, diffs: list[FileDiff]) -> list[PeerFile]:
    """For each *new* source file in *diffs*, find existing files in the same directory
    with the same extension — those are structural peers.

    Returns the top peers sorted by name similarity to the new file.
    """
    peers: list[PeerFile] = []
    seen: set[str] = set()

    new_files = [d for d in diffs if d.status == "added" and d.kind == FileKind.SOURCE]

    for diff in new_files:
        directory = str(Path(diff.path).parent)
        ext = Path(diff.path).suffix
        new_name = Path(diff.path).stem

        # List all files currently in that directory
        all_files = list_directory_at_head(repo_path, directory)
        same_ext = [
            f for f in all_files
            if f.endswith(ext) and f != diff.path
        ]

        # Score by name similarity (shared prefix/suffix characters)
        scored: list[tuple[float, str]] = []
        for f in same_ext:
            name = Path(f).stem
            score = _name_similarity(new_name, name)
            scored.append((score, f))

        scored.sort(reverse=True)

        for _, peer_path in scored[:MAX_PEER_FILES]:
            if peer_path in seen:
                continue
            seen.add(peer_path)

            content = read_file_at_head(repo_path, peer_path)
            excerpt = get_excerpt(content, MAX_PEER_LINES) if content else "(could not read)"

            peers.append(PeerFile(
                path=peer_path,
                content_excerpt=excerpt,
                similarity_reason=f"same directory ({directory}), same extension ({ext})",
            ))

    return peers


def _name_similarity(a: str, b: str) -> float:
    """Simple character-overlap similarity between two names."""
    set_a = set(a.lower())
    set_b = set(b.lower())
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    return len(intersection) / max(len(set_a), len(set_b))


def reconstruct_before_state(diffs: list[FileDiff]) -> list[EvidenceItem]:
    """Produce evidence items describing the before-state based on the diff.

    For added files: "This type/module did not exist before this commit."
    For modified files: note the removed lines.
    """
    items: list[EvidenceItem] = []

    for diff in diffs:
        if diff.status == "added" and diff.kind == FileKind.SOURCE:
            items.append(EvidenceItem(
                content=(
                    f"File `{diff.path}` was **new in this commit** — "
                    f"it did not exist in the parent commit. "
                    f"This means the `{Path(diff.path).stem}` type/module was introduced here."
                ),
                source_file=diff.path,
                source_line=None,
                kind=ClaimKind.INFERRED,
                label=f"New file: {diff.path}",
            ))

        elif diff.status == "modified" and diff.removed_lines:
            # Only keep the first few removed lines as evidence of the before-state
            before_excerpt = "\n".join(diff.removed_lines[:20])
            if before_excerpt.strip():
                items.append(EvidenceItem(
                    content=(
                        f"Before this commit, `{diff.path}` contained the following "
                        f"(now-removed) lines:\n```\n{before_excerpt}\n```"
                    ),
                    source_file=diff.path,
                    source_line=None,
                    kind=ClaimKind.INFERRED,
                    label=f"Modified file before-state: {diff.path}",
                ))

    return items


def extract_test_assertions(test_contents: dict[str, str]) -> list[EvidenceItem]:
    """Parse test files for meaningful assertions and comments that reveal intent."""
    items: list[EvidenceItem] = []

    for path, content in test_contents.items():
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Grab comments that explain behaviour
            if (
                stripped.startswith("#") and len(stripped) > 5
                and not stripped.startswith("# noqa")
                and not stripped.startswith("# type:")
            ):
                items.append(EvidenceItem(
                    content=stripped,
                    source_file=path,
                    source_line=i,
                    kind=ClaimKind.INFERRED,
                    label=f"Test comment in {Path(path).name}:{i}",
                ))
            # Grab assert statements with interesting expressions
            elif stripped.startswith("assert ") and len(stripped) < 120:
                items.append(EvidenceItem(
                    content=stripped,
                    source_file=path,
                    source_line=i,
                    kind=ClaimKind.INFERRED,
                    label=f"Test assertion in {Path(path).name}:{i}",
                ))

    # Limit to the most informative items (comments first)
    comments = [e for e in items if e.content.startswith("#")]
    asserts = [e for e in items if not e.content.startswith("#")]
    return (comments[:10] + asserts[:10])
