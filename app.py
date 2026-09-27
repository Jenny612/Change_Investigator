"""
Change Investigator — Flask web UI

Start with:  python app.py
Then open:   http://localhost:5000
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
from pathlib import Path

# Ensure the project root is importable (same as investigate.py)
sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, Response, jsonify, render_template, request

from collectors import git_collector, history_collector, source_collector
from analysis import diff_parser, pattern_detector, symbol_extractor
from synthesis import llm_synthesiser
from models import InvestigationContext

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Pipeline runner (replicates investigate.py logic, no print side-effects)
# ---------------------------------------------------------------------------

def _run_pipeline(repo_path: str, sha: str, progress_q: queue.Queue) -> dict:
    """Run the full investigation pipeline.

    Puts string progress messages into *progress_q* as work proceeds.
    Returns a dict with keys: commit, report, context_summary, elapsed.
    Raises on hard errors so the caller can catch and report them.
    """
    def _progress(msg: str) -> None:
        progress_q.put(msg)

    t0 = time.time()
    repo_path = str(Path(repo_path).resolve())

    _progress("Fetching commit metadata...")
    commit = git_collector.get_commit_info(repo_path, sha)
    _progress(f"Commit: {commit.subject[:80]}")

    _progress("Fetching diff...")
    raw_diff = git_collector.get_raw_diff(repo_path, sha)

    _progress("Fetching surrounding commits...")
    git_collector.get_surrounding_commits(repo_path, sha, n=5)

    _progress("Parsing diff...")
    diffs = diff_parser.parse_diff(raw_diff)
    added = sum(1 for d in diffs if d.status == "added")
    modified = sum(1 for d in diffs if d.status == "modified")
    _progress(f"Parsed {len(diffs)} files ({added} added, {modified} modified)")

    _progress("Extracting new symbols...")
    raw_symbols = symbol_extractor.extract_new_symbols(diffs)
    symbols = symbol_extractor.prioritise_symbols(raw_symbols)

    _progress("Reading new source files...")
    new_file_contents = source_collector.read_new_files(repo_path, diffs)

    _progress("Reading test files...")
    test_file_contents = source_collector.read_test_files(repo_path, diffs)

    _progress("Searching for symbol references...")
    grep_matches = source_collector.grep_for_symbols(repo_path, symbols, max_symbols=10)

    _progress("Finding structural peer files...")
    peer_files = pattern_detector.find_peer_files(repo_path, diffs)

    _progress("Reconstructing before-state...")
    before_evidence = pattern_detector.reconstruct_before_state(diffs)

    _progress("Extracting test assertions...")
    test_evidence = pattern_detector.extract_test_assertions(test_file_contents)

    evidence_items = before_evidence + test_evidence

    _progress("Searching changelog/history...")
    changelog_entry = None
    if commit.pr_number:
        changelog_entry = history_collector.find_changelog_entry(repo_path, commit.pr_number)

    _progress("Finding sibling commits...")
    sibling_commits = history_collector.find_sibling_commits(repo_path, sha)

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

    _progress("Synthesising report...")
    report = llm_synthesiser.synthesise(ctx)

    elapsed = time.time() - t0
    _progress(f"Done in {elapsed:.1f}s")

    # Build a JSON-serialisable summary of the context for the UI
    context_summary = {
        "files_changed": len(diffs),
        "new_source_files": [d.path for d in diffs if d.status == "added" and d.kind.value == "source"],
        "test_files": list(test_file_contents.keys()),
        "peer_files": [{"path": p.path, "reason": p.similarity_reason} for p in peer_files[:5]],
        "sibling_commits": [
            {"sha": s.sha, "subject": s.subject, "pr": s.pr_number}
            for s in sibling_commits[:8]
        ],
        "symbols_found": symbols[:12],
        "grep_hit_count": sum(len(v) for v in grep_matches.values()),
        "changelog_found": changelog_entry is not None,
    }

    return {
        "commit": {
            "sha": commit.sha,
            "short_sha": commit.short_sha,
            "subject": commit.subject,
            "author": commit.author,
            "date": commit.date,
            "pr_number": commit.pr_number,
        },
        "report": {
            "was_synthesised": report.was_synthesised,
            "change": report.change.content,
            "before_after": report.before_after.content,
            "problem_addressed": report.problem_addressed.content,
            "evidence": report.evidence.content,
            "confidence": report.confidence.content,
        },
        "context_summary": context_summary,
        "elapsed": round(elapsed, 1),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/investigate", methods=["POST"])
def investigate():
    data = request.get_json(force=True)
    repo_path = (data.get("repo") or "").strip()
    sha = (data.get("commit") or "").strip()

    if not repo_path or not sha:
        return jsonify({"error": "repo and commit are required"}), 400

    repo = Path(repo_path)
    if not repo.exists():
        return jsonify({"error": f"Repository path not found: {repo_path}"}), 400
    if not (repo / ".git").exists():
        return jsonify({"error": f"Not a git repository: {repo_path}"}), 400

    try:
        result = _run_pipeline(repo_path, sha, queue.Queue())
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    print("Change Investigator UI")
    print("Open http://localhost:5000 in your browser")
    app.run(debug=False, port=5000)
