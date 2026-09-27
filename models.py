"""Shared data models for Change Investigator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FileKind(str, Enum):
    SOURCE = "source"
    TEST = "test"
    DOC = "doc"
    CONFIG = "config"
    OTHER = "other"


class ClaimKind(str, Enum):
    DOCUMENTED = "documented"
    INFERRED = "inferred from code"
    RECONSTRUCTED = "reconstructed from pattern"


@dataclass
class CommitInfo:
    sha: str
    short_sha: str
    subject: str
    body: str
    author: str
    date: str
    pr_number: Optional[str] = None  # extracted from message, e.g. "13824"

    @property
    def full_message(self) -> str:
        if self.body:
            return f"{self.subject}\n\n{self.body}"
        return self.subject


@dataclass
class HunkLine:
    kind: str  # "context", "added", "removed"
    content: str


@dataclass
class FileDiff:
    path: str                          # path in new tree (or old if deleted)
    old_path: Optional[str]            # non-None if renamed
    status: str                        # "added", "modified", "deleted", "renamed"
    kind: FileKind
    language: str                      # "python", "rust", "markdown", "other"
    raw_diff: str                      # full unified diff for this file
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)
    before_content: Optional[str] = None   # content at parent commit (None if added)
    after_content: Optional[str] = None    # content at this commit (None if deleted)

    @property
    def is_new_file(self) -> bool:
        return self.status == "added"

    @property
    def is_test(self) -> bool:
        return self.kind == FileKind.TEST

    @property
    def is_doc(self) -> bool:
        return self.kind == FileKind.DOC


@dataclass
class GrepMatch:
    file_path: str
    line_number: int
    line_content: str
    symbol: str


@dataclass
class PeerFile:
    path: str
    content_excerpt: str   # first 40 lines
    similarity_reason: str  # e.g. "same directory, same extension"


@dataclass
class SiblingCommit:
    sha: str
    subject: str
    pr_number: Optional[str]


@dataclass
class EvidenceItem:
    content: str
    source_file: str
    source_line: Optional[int]
    kind: ClaimKind
    label: str   # short human label, e.g. "Test file asserts strict mode behaviour"


@dataclass
class InvestigationContext:
    commit: CommitInfo
    diffs: list[FileDiff]
    new_file_contents: dict[str, str]        # path -> full content
    test_file_contents: dict[str, str]       # path -> full content
    grep_matches: dict[str, list[GrepMatch]] # symbol -> matches
    peer_files: list[PeerFile]
    sibling_commits: list[SiblingCommit]
    changelog_entry: Optional[str]
    evidence_items: list[EvidenceItem] = field(default_factory=list)

    @property
    def all_new_symbols(self) -> list[str]:
        return list(self.grep_matches.keys())

    @property
    def changed_file_paths(self) -> list[str]:
        return [d.path for d in self.diffs]

    @property
    def new_source_files(self) -> list[FileDiff]:
        return [d for d in self.diffs if d.is_new_file and d.kind == FileKind.SOURCE]

    @property
    def test_files(self) -> list[FileDiff]:
        return [d for d in self.diffs if d.is_test]

    @property
    def doc_files(self) -> list[FileDiff]:
        return [d for d in self.diffs if d.is_doc]


@dataclass
class ReportSection:
    title: str
    content: str


@dataclass
class Report:
    sha: str
    pr_number: Optional[str]
    commit_subject: str

    change: ReportSection
    before_after: ReportSection
    problem_addressed: ReportSection
    evidence: ReportSection
    confidence: ReportSection

    raw_llm_response: Optional[str] = None
    was_synthesised: bool = True   # False if LLM failed and fallback was used

    @property
    def sections(self) -> list[ReportSection]:
        return [
            self.change,
            self.before_after,
            self.problem_addressed,
            self.evidence,
            self.confidence,
        ]
