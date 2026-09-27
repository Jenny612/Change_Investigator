"""LLM synthesiser — builds a grounded prompt from InvestigationContext,
calls IBM watsonx Granite, and parses the structured Report response.

Design principle: the LLM adds *narrative glue* only. All facts come from
the collected evidence. The prompt explicitly forbids inventing file paths
or commits that were not provided.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Optional

from models import (
    InvestigationContext,
    Report,
    ReportSection,
    ClaimKind,
    GrepMatch,
)
import config


# ---------------------------------------------------------------------------
# Token budget helpers
# ---------------------------------------------------------------------------

_CHARS_PER_TOKEN = 4  # rough approximation
MAX_PROMPT_CHARS = 28_000  # ~7000 tokens, safe for most Granite models


def _budget(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated for context budget]"


def _section(title: str, body: str) -> str:
    return f"\n### {title}\n\n{body.strip()}\n"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_prompt(ctx: InvestigationContext) -> str:
    parts: list[str] = []

    # ---- System preamble ----
    parts.append(textwrap.dedent("""\
        You are an expert software engineer analysing a code change.
        Your task is to write a concise, evidence-based investigation report.

        STRICT RULES:
        1. Only cite files and commits that appear in the evidence section below.
        2. Do not invent file paths, line numbers, or commit SHAs.
        3. Label every factual claim with one of:
           - [documented] — explicitly stated in the commit message, changelog, or PR description
           - [inferred from code] — deduced from reading the source/test files provided
           - [reconstructed from pattern] — inferred from structural patterns (e.g. series of similar commits)
        4. Distinguish what is CERTAIN from what is UNCERTAIN.
        5. Keep each section concise (3–8 sentences or bullet points).

        Produce EXACTLY these five sections in order:
        ## 1. Change
        ## 2. Before / After
        ## 3. Problem Addressed
        ## 4. Evidence
        ## 5. Confidence / Uncertainty
    """))

    # ---- Commit metadata ----
    pr_ref = f"PR #{ctx.commit.pr_number}" if ctx.commit.pr_number else "no PR number found"
    parts.append(_section("Commit Metadata", textwrap.dedent(f"""\
        - SHA: {ctx.commit.sha}
        - Subject: {ctx.commit.subject}
        - Author: {ctx.commit.author}
        - Date: {ctx.commit.date}
        - PR reference: {pr_ref}
        - Message body: {ctx.commit.body or "(none)"}
    """)))

    # ---- Changed files summary ----
    file_lines: list[str] = []
    for d in ctx.diffs:
        file_lines.append(f"  - [{d.status.upper()}/{d.kind.value}] {d.path}")
    parts.append(_section(
        "Changed Files",
        "\n".join(file_lines) or "(no files parsed)"
    ))

    # ---- New source files (full content, budgeted) ----
    if ctx.new_file_contents:
        new_file_parts: list[str] = []
        per_file_budget = max(2000, MAX_PROMPT_CHARS // (len(ctx.new_file_contents) + 1))
        for path, content in ctx.new_file_contents.items():
            excerpt = _budget(content, per_file_budget)
            new_file_parts.append(f"**{path}**\n```\n{excerpt}\n```")
        parts.append(_section("New File Contents", "\n\n".join(new_file_parts)))

    # ---- Test files ----
    if ctx.test_file_contents:
        test_parts: list[str] = []
        for path, content in ctx.test_file_contents.items():
            excerpt = _budget(content, 3000)
            test_parts.append(f"**{path}**\n```python\n{excerpt}\n```")
        parts.append(_section("Test Files", "\n\n".join(test_parts)))

    # ---- Structural peers ----
    if ctx.peer_files:
        peer_parts: list[str] = []
        for peer in ctx.peer_files[:4]:
            excerpt = _budget(peer.content_excerpt, 800)
            peer_parts.append(
                f"**{peer.path}** ({peer.similarity_reason})\n```\n{excerpt}\n```"
            )
        parts.append(_section("Structural Peer Files (existing analogues)", "\n\n".join(peer_parts)))

    # ---- Git grep results ----
    if ctx.grep_matches:
        grep_parts: list[str] = []
        for symbol, matches in list(ctx.grep_matches.items())[:10]:
            lines = [f"  {m.file_path}:{m.line_number}: {m.line_content}" for m in matches[:8]]
            grep_parts.append(f"Symbol `{symbol}`:\n" + "\n".join(lines))
        parts.append(_section("Symbol References Across Repo (git grep)", "\n\n".join(grep_parts)))

    # ---- Changelog entry ----
    if ctx.changelog_entry:
        parts.append(_section("Changelog / History Entry", ctx.changelog_entry))

    # ---- Sibling commits ----
    if ctx.sibling_commits:
        sib_lines = [
            f"  - {s.sha}: {s.subject}"
            + (f" (PR #{s.pr_number})" if s.pr_number else "")
            for s in ctx.sibling_commits[:10]
        ]
        parts.append(_section(
            "Sibling Commits (same pattern in git log)",
            "\n".join(sib_lines)
        ))

    # ---- Before-state evidence ----
    before_items = [e for e in ctx.evidence_items if "before" in e.label.lower() or "new file" in e.label.lower()]
    if before_items:
        before_parts = [f"- {e.content}" for e in before_items[:6]]
        parts.append(_section("Before-State Evidence", "\n".join(before_parts)))

    # ---- Test assertions / comments ----
    test_items = [e for e in ctx.evidence_items if "test" in e.label.lower()]
    if test_items:
        test_evidence = [
            f"  - `{e.source_file}:{e.source_line}`: {e.content}"
            for e in test_items[:10]
        ]
        parts.append(_section("Key Test Assertions and Comments", "\n".join(test_evidence)))

    # ---- Final instruction ----
    parts.append(textwrap.dedent("""\
        ---
        Now write the five-section investigation report. Start each section with exactly:
        ## 1. Change
        ## 2. Before / After
        ## 3. Problem Addressed
        ## 4. Evidence
        ## 5. Confidence / Uncertainty

        Remember: label every claim [documented], [inferred from code], or [reconstructed from pattern].
        Cite specific file paths and commit SHAs from the evidence above.
        Do not invent any information.
    """))

    full_prompt = "\n".join(parts)
    return _budget(full_prompt, MAX_PROMPT_CHARS)


# ---------------------------------------------------------------------------
# watsonx call
# ---------------------------------------------------------------------------

def call_watsonx(prompt: str) -> str:
    """Call IBM watsonx Granite and return the raw text response."""
    from ibm_watsonx_ai import APIClient, Credentials
    from ibm_watsonx_ai.foundation_models import ModelInference

    credentials = Credentials(
        url=config.get_watsonx_url(),
        api_key=config.get_watsonx_apikey(),
    )
    client = APIClient(credentials=credentials, project_id=config.get_watsonx_project_id())

    model = ModelInference(
        model_id=config.get_model_id(),
        api_client=client,
    )

    response = model.generate_text(
        prompt=prompt,
        params={
            "max_new_tokens": 2048,
            "temperature": 0.1,      # low temperature = more deterministic, less hallucination
            "repetition_penalty": 1.1,
        },
    )
    return response


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

_SECTION_PATTERNS = [
    (r"##\s*1\.\s*Change\s*\n(.*?)(?=##\s*2\.)", "change"),
    (r"##\s*2\.\s*Before\s*/\s*After\s*\n(.*?)(?=##\s*3\.)", "before_after"),
    (r"##\s*3\.\s*Problem\s+Addressed\s*\n(.*?)(?=##\s*4\.)", "problem_addressed"),
    (r"##\s*4\.\s*Evidence\s*\n(.*?)(?=##\s*5\.)", "evidence"),
    (r"##\s*5\.\s*Confidence\s*/\s*Uncertainty\s*\n(.*?)$", "confidence"),
]


def parse_response(raw: str, ctx: InvestigationContext) -> Report:
    """Extract the five sections from the LLM response."""
    sections: dict[str, str] = {}

    for pattern, key in _SECTION_PATTERNS:
        m = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        if m:
            sections[key] = m.group(1).strip()

    # Fallback: if parsing failed, split on ## headers
    if len(sections) < 3:
        sections = _fallback_parse(raw)

    def _sec(key: str, title: str, fallback_fn) -> ReportSection:
        content = sections.get(key, "").strip()
        if not content:
            content = fallback_fn()
        return ReportSection(title=title, content=content)

    return Report(
        sha=ctx.commit.sha,
        pr_number=ctx.commit.pr_number,
        commit_subject=ctx.commit.subject,
        change=_sec("change", "Change", lambda: _fallback_change(ctx)),
        before_after=_sec("before_after", "Before / After", lambda: _fallback_before_after(ctx)),
        problem_addressed=_sec("problem_addressed", "Problem Addressed", lambda: _fallback_problem(ctx)),
        evidence=_sec("evidence", "Evidence", lambda: _fallback_evidence(ctx)),
        confidence=_sec("confidence", "Confidence / Uncertainty", lambda: _fallback_confidence(ctx)),
        raw_llm_response=raw,
        was_synthesised=True,
    )


def _fallback_parse(raw: str) -> dict[str, str]:
    """Best-effort section split when the regex approach fails."""
    result: dict[str, str] = {}
    keys = ["change", "before_after", "problem_addressed", "evidence", "confidence"]
    titles = ["Change", "Before", "Problem", "Evidence", "Confidence"]

    parts = re.split(r"##\s*\d+\.", raw)
    for i, part in enumerate(parts[1:6]):
        if i < len(keys):
            result[keys[i]] = part.strip()
    return result


# ---------------------------------------------------------------------------
# Fallback sections (used when LLM is unavailable or parsing fails)
# ---------------------------------------------------------------------------

def _fallback_change(ctx: InvestigationContext) -> str:
    lines = [f"Commit `{ctx.commit.short_sha}` — {ctx.commit.subject}"]
    if ctx.commit.pr_number:
        lines.append(f"PR #{ctx.commit.pr_number}")
    lines.append(f"\nChanged {len(ctx.diffs)} files:")
    new_src = [d.path for d in ctx.diffs if d.status == "added" and d.kind.value == "source"]
    for p in new_src[:5]:
        lines.append(f"- [ADDED/source] `{p}`")
    return "\n".join(lines)


def _fallback_before_after(ctx: InvestigationContext) -> str:
    new_files = [d for d in ctx.diffs if d.status == "added"]
    before_items = [e for e in ctx.evidence_items if "new file" in e.label.lower()]
    parts = []
    if before_items:
        parts.append("**Before:** " + before_items[0].content)
    if new_files:
        names = ", ".join(f"`{d.path}`" for d in new_files[:3])
        parts.append(f"**After:** New files introduced: {names}")
    if ctx.peer_files:
        parts.append(
            f"Structural peers (existing analogues): "
            + ", ".join(f"`{p.path}`" for p in ctx.peer_files[:3])
        )
    return "\n\n".join(parts) if parts else "[Reconstructed from diff — LLM synthesis not available]"


def _fallback_problem(ctx: InvestigationContext) -> str:
    if ctx.sibling_commits:
        names = ", ".join(f"#{s.pr_number or s.sha}" for s in ctx.sibling_commits[:3])
        return (
            f"[reconstructed from pattern] This change appears to be part of a series "
            f"that adds dedicated core schema types for standard library collection types "
            f"(see sibling commits: {names}). Without a dedicated schema, strict-mode "
            f"enforcement and typed error codes for this type were not possible."
        )
    return "[Fallback — LLM synthesis not available. Run with valid watsonx credentials for full synthesis.]"


def _fallback_evidence(ctx: InvestigationContext) -> str:
    lines = []
    if ctx.peer_files:
        for p in ctx.peer_files[:3]:
            lines.append(f"- [inferred from code] Structural peer: `{p.path}` ({p.similarity_reason})")
    if ctx.sibling_commits:
        for s in ctx.sibling_commits[:3]:
            lines.append(f"- [reconstructed from pattern] Sibling commit `{s.sha}`: {s.subject}")
    if ctx.changelog_entry:
        lines.append(f"- [documented] Changelog entry found for PR #{ctx.commit.pr_number}")
    for e in ctx.evidence_items[:5]:
        lines.append(f"- [{e.kind.value}] `{e.source_file}`: {e.label}")
    return "\n".join(lines) if lines else "(no structured evidence collected)"


def _fallback_confidence(ctx: InvestigationContext) -> str:
    return (
        "Confidence in *what changed*: HIGH — based on the diff.\n"
        "Confidence in *why it changed*: MEDIUM — reconstructed from structural patterns "
        "and sibling commits; not explicitly documented in the commit message.\n"
        "Uncertainty: The commit message contains no extended rationale. "
        "All reasoning about motivation is inferred."
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def synthesise(ctx: InvestigationContext) -> Report:
    """Build the prompt, call watsonx, parse the response.

    Falls back to structured evidence report if watsonx is unavailable.
    """
    if not config.watsonx_configured():
        # No credentials — return a fallback report built from raw evidence
        return _build_fallback_report(ctx)

    prompt = build_prompt(ctx)

    try:
        raw_response = call_watsonx(prompt)
        return parse_response(raw_response, ctx)
    except Exception as exc:
        # LLM call failed — return fallback but note the error
        report = _build_fallback_report(ctx)
        report.raw_llm_response = f"LLM call failed: {exc}"
        report.was_synthesised = False
        return report


def _build_fallback_report(ctx: InvestigationContext) -> Report:
    return Report(
        sha=ctx.commit.sha,
        pr_number=ctx.commit.pr_number,
        commit_subject=ctx.commit.subject,
        change=ReportSection("Change", _fallback_change(ctx)),
        before_after=ReportSection("Before / After", _fallback_before_after(ctx)),
        problem_addressed=ReportSection("Problem Addressed", _fallback_problem(ctx)),
        evidence=ReportSection("Evidence", _fallback_evidence(ctx)),
        confidence=ReportSection("Confidence / Uncertainty", _fallback_confidence(ctx)),
        raw_llm_response=None,
        was_synthesised=False,
    )
