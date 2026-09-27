#!/usr/bin/env python3
"""
Change Investigator CLI

Usage:
    python investigate.py --repo <repo_path> --commit <sha> [--output <output_dir>]

Example:
    python investigate.py --repo ../source/pydantic --commit 617abdb1b
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path so sibling packages resolve
sys.path.insert(0, str(Path(__file__).parent))

from models import InvestigationContext, EvidenceItem
from collectors import git_collector, source_collector, history_collector
from analysis import diff_parser, symbol_extractor, pattern_detector
from synthesis import llm_synthesiser
from report import renderer


def _print_step(msg: str) -> None:
    try:
        from rich.console import Console
        Console().print(f"  [dim]->[/dim] {msg}")
    except ImportError:
        print(f"  -> {msg}")


def _print_header(msg: str) -> None:
    try:
        from rich.console import Console
        Console().print(f"\n[bold blue]{msg}[/bold blue]")
    except ImportError:
        print(f"\n{msg}")


def _print_success(msg: str) -> None:
    try:
        from rich.console import Console
        Console().print(f"[green]ok[/green] {msg}")
    except ImportError:
        print(f"ok {msg}")


def _print_warning(msg: str) -> None:
    try:
        from rich.console import Console
        Console().print(f"[yellow]![/yellow]  {msg}")
    except ImportError:
        print(f"!  {msg}")


def investigate(repo_path: str, sha: str, output_dir: str) -> None:
    t0 = time.time()
    repo_path = str(Path(repo_path).resolve())

    # -----------------------------------------------------------------------
    # Phase 1: Git collection
    # -----------------------------------------------------------------------
    _print_header("Phase 1 - Git collection")

    _print_step("Fetching commit metadata...")
    commit = git_collector.get_commit_info(repo_path, sha)
    _print_success(
        f"Commit {commit.short_sha}: {commit.subject[:70]}"
        + (f" (PR #{commit.pr_number})" if commit.pr_number else "")
    )

    _print_step("Fetching raw diff...")
    raw_diff = git_collector.get_raw_diff(repo_path, sha)

    _print_step("Fetching surrounding commits...")
    surrounding = git_collector.get_surrounding_commits(repo_path, sha, n=5)
    _print_success(f"Found {len(surrounding)} surrounding commits")

    # -----------------------------------------------------------------------
    # Phase 2a: Diff parsing & symbol extraction
    # -----------------------------------------------------------------------
    _print_header("Phase 2 - Evidence collection")

    _print_step("Parsing diff...")
    diffs = diff_parser.parse_diff(raw_diff)
    _print_success(
        f"Parsed {len(diffs)} file diffs "
        f"({sum(1 for d in diffs if d.status=='added')} added, "
        f"{sum(1 for d in diffs if d.status=='modified')} modified)"
    )

    _print_step("Extracting new symbols...")
    raw_symbols = symbol_extractor.extract_new_symbols(diffs)
    symbols = symbol_extractor.prioritise_symbols(raw_symbols)
    _print_success(f"Extracted {len(symbols)} symbols: {', '.join(symbols[:8])}")

    # -----------------------------------------------------------------------
    # Phase 2b: Source collection
    # -----------------------------------------------------------------------
    _print_step("Reading new source files...")
    new_file_contents = source_collector.read_new_files(repo_path, diffs)
    _print_success(f"Read {len(new_file_contents)} new source files")

    _print_step("Reading test files...")
    test_file_contents = source_collector.read_test_files(repo_path, diffs)
    _print_success(f"Read {len(test_file_contents)} test files")

    _print_step("Running git grep for new symbols...")
    grep_matches = source_collector.grep_for_symbols(repo_path, symbols, max_symbols=10)
    total_grep = sum(len(v) for v in grep_matches.values())
    _print_success(f"Found {total_grep} grep matches across {len(grep_matches)} symbols")

    # -----------------------------------------------------------------------
    # Phase 2c: Pattern detection
    # -----------------------------------------------------------------------
    _print_step("Finding structural peer files...")
    peer_files = pattern_detector.find_peer_files(repo_path, diffs)
    if peer_files:
        _print_success(f"Found {len(peer_files)} peer files: {', '.join(p.path for p in peer_files[:3])}")
    else:
        _print_warning("No structural peers found")

    _print_step("Reconstructing before-state...")
    before_evidence = pattern_detector.reconstruct_before_state(diffs)

    _print_step("Extracting test assertions...")
    test_evidence = pattern_detector.extract_test_assertions(test_file_contents)

    evidence_items = before_evidence + test_evidence

    # -----------------------------------------------------------------------
    # Phase 2d: History collection
    # -----------------------------------------------------------------------
    _print_step("Searching changelog/history...")
    changelog_entry = None
    if commit.pr_number:
        changelog_entry = history_collector.find_changelog_entry(repo_path, commit.pr_number)
        if changelog_entry:
            _print_success(f"Found changelog entry for PR #{commit.pr_number}")
        else:
            _print_warning(f"No changelog entry found for PR #{commit.pr_number}")
    else:
        _print_warning("No PR number in commit message - skipping changelog search")

    _print_step("Finding sibling commits...")
    sibling_commits = history_collector.find_sibling_commits(repo_path, sha)
    if sibling_commits:
        _print_success(f"Found {len(sibling_commits)} sibling commits")
    else:
        _print_warning("No sibling commits found")

    # Also scan changelog for the series
    if commit.pr_number:
        series_lines = history_collector.scan_changelog_for_series(repo_path, commit.pr_number)
        if series_lines:
            _print_success(f"Found {len(series_lines)} related changelog lines")

    # -----------------------------------------------------------------------
    # Assemble InvestigationContext
    # -----------------------------------------------------------------------
    ctx = InvestigationContext(
        commit=commit,
        diffs=diffs,
        new_file_contents=new_file_contents,
        test_file_contents=test_file_contents,
        grep_matches=grep_matches,
        peer_files=peer_files,
        sibling_commits=sibling_commits,
        changelog_entry=changelog_entry,
        evidence_items=evidence_items,
    )

    # -----------------------------------------------------------------------
    # Phase 3: LLM synthesis
    # -----------------------------------------------------------------------
    _print_header("Phase 3 - LLM synthesis")

    import config as cfg
    if cfg.watsonx_configured():
        _print_step("Calling IBM watsonx Granite...")
    else:
        _print_warning(
            "watsonx not configured - producing evidence-based fallback report.\n"
            "    Set WATSONX_URL, WATSONX_APIKEY, WATSONX_PROJECT_ID in .env for full synthesis."
        )

    report = llm_synthesiser.synthesise(ctx)

    if report.was_synthesised:
        _print_success("LLM synthesis complete")
    else:
        if report.raw_llm_response and report.raw_llm_response.startswith("LLM call failed"):
            _print_warning(f"LLM call failed: {report.raw_llm_response[:120]}")
        else:
            _print_success("Fallback report built from collected evidence")

    # -----------------------------------------------------------------------
    # Phase 4: Render & save
    # -----------------------------------------------------------------------
    _print_header("Phase 4 - Rendering")

    report_path = renderer.save_report(report, ctx, output_dir)
    _print_success(f"Report saved -> {report_path}")

    renderer.render_terminal(report, ctx)

    elapsed = time.time() - t0
    _print_header(f"Done in {elapsed:.1f}s")  # no unicode needed here
    print(f"\n  Report: {report_path}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Investigate a Git commit and reconstruct the rationale behind the change.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python investigate.py --repo ../source/pydantic --commit 617abdb1b
  python investigate.py --repo /path/to/repo --commit abc1234 --output ./my-reports
        """,
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="Path to the local Git repository to investigate.",
    )
    parser.add_argument(
        "--commit",
        required=True,
        help="Commit SHA (full or abbreviated) to investigate.",
    )
    parser.add_argument(
        "--output",
        default="./output",
        help="Directory to write the Markdown report (default: ./output).",
    )
    args = parser.parse_args()

    repo = Path(args.repo)
    if not repo.exists():
        print(f"Error: repository path does not exist: {repo}", file=sys.stderr)
        sys.exit(1)

    git_dir = repo / ".git"
    if not git_dir.exists():
        print(f"Error: not a git repository: {repo}", file=sys.stderr)
        sys.exit(1)

    try:
        investigate(str(repo), args.commit, args.output)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
