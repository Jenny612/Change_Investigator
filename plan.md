# Change Investigator — MVP Plan

## Top-Level Overview

**Goal:** Build a CLI tool that takes a local Git repository and a commit SHA, collects
evidence from Git history, source code, tests, and documentation, and produces a
structured, evidence-grounded investigation report explaining *why* the change was made.

**Validation case:** Pydantic commit `617abdb1b` ("Add a `counter` core schema (#13824)").
The tool must reproduce — automatically — the investigation report that was written manually
during the IBM Bob Hackathon research session.

**Scope constraint:** Focused, working CLI over broad platform. No web UI, no GitHub API,
no AST parsing. Every claim in the output must cite a file path or commit SHA.

**LLM role:** Synthesis only. All file reads, diffs, and greps happen in deterministic Python
first. The LLM sees pre-collected structured evidence and produces the narrative report.

---

## Architecture Summary

```
CLI (investigate.py)
  └── Phase 1: Git Collection
        git_collector.py → CommitInfo + list[FileDiff]
  └── Phase 2: Evidence Collection
        diff_parser.py       → structured FileDiff objects
        symbol_extractor.py  → new symbols from diff
        source_collector.py  → file contents + git grep results
        pattern_detector.py  → structural peers + commit series
        history_collector.py → CHANGELOG entry
  └── Phase 3: LLM Synthesis
        llm_synthesiser.py   → InvestigationContext → Report (watsonx)
  └── Phase 4: Rendering
        renderer.py          → Markdown file + terminal output
```

---

## Sub-Tasks

---

### Sub-Task 1: Project Skeleton + Models

**Intent**
Establish the project layout, shared data models, CLI entry point, and config so that all
subsequent sub-tasks have a stable interface to build against.

**Expected Outcomes**
- `change-investigator/` has the full directory structure
- `models.py` defines all shared dataclasses
- `investigate.py` parses `--repo` and `--commit` and prints a placeholder
- `requirements.txt` lists all dependencies
- `.env.example` documents required env vars

**Todo List**
- [ ] Create `change-investigator/investigate.py` with argparse CLI (`--repo`, `--commit`, `--output`)
- [ ] Create `change-investigator/models.py` with dataclasses: `CommitInfo`, `FileDiff`, `EvidenceItem`, `InvestigationContext`, `Report`
- [ ] Create `change-investigator/config.py` loading `.env` for WATSONX_URL, WATSONX_APIKEY, WATSONX_PROJECT_ID, MODEL_ID
- [ ] Create `change-investigator/requirements.txt` (python-dotenv, ibm-watsonx-ai, rich, unidiff)
- [ ] Create `change-investigator/.env.example`
- [ ] Create stub files for all modules (collectors/, analysis/, synthesis/, report/)
- [ ] Create `change-investigator/output/.gitkeep` and add `output/*.md` to `.gitignore`
- [ ] Create `change-investigator/README.md` with setup instructions

**Relevant Context**
- No existing code in `change-investigator/`
- The validation run is: `python investigate.py --repo ../source/pydantic --commit 617abdb1b`
- All paths in the tool are relative to the repo root passed via `--repo`

**Status:** [ ] pending

---

### Sub-Task 2: Git Collector

**Intent**
Extract all raw Git data for the target commit: diff, metadata, commit message, surrounding
commits. This is the foundational data every other phase depends on.

**Expected Outcomes**
- `git_collector.py` returns a `CommitInfo` and list of `FileDiff` objects for any commit SHA
- The diff includes before/after content for each changed file (not just unified diff text)
- Surrounding commits (±10) are returned as a list of `CommitInfo`
- The PR number is extracted from the commit message if present (e.g. `(#13824)`)
- Running against `617abdb1b` returns the correct commit message, 20+ changed files, and PR `13824`

**Todo List**
- [ ] Implement `get_commit_info(repo_path, sha) -> CommitInfo` using `git show --no-patch --format=...`
- [ ] Implement `get_raw_diff(repo_path, sha) -> str` using `git show <sha>`
- [ ] Implement `get_file_at_parent(repo_path, sha, file_path) -> str | None` using `git show <sha>^:<file>`
- [ ] Implement `get_surrounding_commits(repo_path, sha, n=10) -> list[CommitInfo]` using `git log`
- [ ] Extract PR number from commit message body via regex `\(#(\d+)\)`
- [ ] Wire into `investigate.py` — print CommitInfo on run
- [ ] Test: running against `617abdb1b` prints correct commit message and file count

**Relevant Context**
- Git objects are in a packfile (`source/pydantic/.git/objects/pack/`) — must use `git` subprocess, not direct object reads
- The repo was cloned once; HEAD = `bb6da4cfbb1f559885ea2fa207ec93853bfeac64`
- `git show <sha> --stat` confirms the commit exists and lists changed files
- Use `subprocess.run(['git', '-C', repo_path, ...])` pattern throughout

**Status:** [ ] pending

---

### Sub-Task 3: Evidence Collectors

**Intent**
Given the raw diff and commit info, collect all supporting evidence from the repository:
full file contents, grep results for new symbols, test files, CHANGELOG entries, and
structural peers (analogous files that already exist).

**Expected Outcomes**
- `diff_parser.py`: parses unified diff into structured `FileDiff` objects with `before`/`after` content and file classification (source | test | doc | config | other)
- `symbol_extractor.py`: from the diff's `+` lines, extracts new symbol names (class names, function names, string constants like `'counter'`)
- `source_collector.py`: reads full content of new/added files; runs `git grep` for each extracted symbol; finds test files
- `pattern_detector.py`: given a new file like `counter.rs`, finds peers in the same directory (`ordered_dict.rs`, `deque.rs`); finds sibling commits via `git log --grep`
- `history_collector.py`: finds the CHANGELOG/HISTORY entry for the extracted PR number
- For `617abdb1b`: surfaces `ordered_dict.rs` as a peer, finds `test_counter.py`, finds PR `#13824` in `HISTORY.md`, finds sibling `#13757` (deque) in HISTORY

**Todo List**
- [ ] Implement `diff_parser.py`: parse unified diff text into `list[FileDiff]`; classify each file by extension and path pattern (`/tests/` → test, `/docs/` → doc, `.rs`/`.py` → source)
- [ ] Implement `symbol_extractor.py`: scan `+` lines in each `FileDiff` for `class Foo`, `def foo`, `fn foo`, `const FOO`, `'counter'`-style string literals; return deduplicated symbol list
- [ ] Implement `source_collector.py`:
  - `read_new_files(repo_path, diffs)` — read full content of added files
  - `grep_for_symbols(repo_path, symbols)` — `git grep` each symbol, return `list[GrepMatch]`
  - `read_test_files(repo_path, diffs)` — read test files in full
- [ ] Implement `pattern_detector.py`:
  - `find_peer_files(repo_path, new_files)` — list files in same directory, same extension, excluding the new file itself
  - `find_sibling_commits(repo_path, sha, title_prefix)` — `git log --oneline --grep="Add a .* core schema"` to find the series
- [ ] Implement `history_collector.py`:
  - `find_changelog_entry(repo_path, pr_number)` — scan HISTORY.md/CHANGELOG.md for `#<pr_number>`, return surrounding paragraph
- [ ] Assemble all collected evidence into `InvestigationContext`
- [ ] Wire into `investigate.py` — print evidence summary on run

**Relevant Context**
- Peer file detection: when `counter.rs` is new in `src/validators/`, the peers are all `.rs` files already there (especially `ordered_dict.rs`)
- Sibling commit detection: git log pattern `"Add a .* core schema"` matches #13505, #13757, #13824
- `unidiff` library can parse unified diff format reliably
- For `617abdb1b`: HISTORY.md line 41 has `#13757` and line 114 has `#13505` — both reachable by text search

**Status:** [ ] pending

---

### Sub-Task 4: LLM Synthesis

**Intent**
Take the `InvestigationContext` (all collected evidence), build a grounded prompt, call
IBM watsonx, and return a structured `Report`. The LLM is strictly instructed to cite
file paths and label claim types — it must not invent facts.

**Expected Outcomes**
- `llm_synthesiser.py` builds a well-structured context string from `InvestigationContext`
- The prompt instructs the model to produce exactly five sections: Change, Before/After, Problem Addressed, Evidence, Confidence/Uncertainty
- Every claim is labelled as `[documented]`, `[inferred from code]`, or `[reconstructed from pattern]`
- The model is instructed: "Only cite files and commits that appear in the evidence I have provided"
- Running against `617abdb1b`: the returned `Report` covers all five sections with specific file citations

**Todo List**
- [ ] Implement `build_prompt(context: InvestigationContext) -> str`
  - Include: commit message, PR number, list of changed files (with classification)
  - Include: full content of new source files (truncated to 200 lines each if needed)
  - Include: before/after excerpts from modified files
  - Include: test file contents
  - Include: peer file names (not full content — just names and first 30 lines)
  - Include: git grep results (file + line number + match)
  - Include: CHANGELOG entry if found
  - Include: sibling commit titles
  - Prompt instructions: five sections, cite files, label claims, no invented facts
- [ ] Implement `call_watsonx(prompt: str) -> str` using `ibm-watsonx-ai` SDK
- [ ] Implement `parse_response(raw: str) -> Report` — extract five sections from model output
- [ ] Add fallback: if LLM call fails, return a `Report` with sections filled from raw evidence (no synthesis)
- [ ] Wire into `investigate.py`

**Relevant Context**
- IBM watsonx model: `ibm/granite-3-3-8b-instruct` (fast) or `ibm/granite-3-3-2b-instruct`
- Credentials from `config.py` / `.env`: `WATSONX_URL`, `WATSONX_APIKEY`, `WATSONX_PROJECT_ID`
- Context window limit: keep total prompt under 8000 tokens; truncate large files from the bottom
- The five sections in the prompt must match the five sections in the `Report` dataclass exactly
- The grounding discipline is the most important property: the LLM adds narrative glue, not new facts

**Status:** [ ] pending

---

### Sub-Task 5: Report Renderer + Polish

**Intent**
Render the `Report` as Markdown (saved to file) and as formatted terminal output. Add
`README.md` instructions and verify the full demo run works end-to-end.

**Expected Outcomes**
- `renderer.py` produces a well-formatted Markdown file in `output/<sha>-report.md`
- Terminal output uses `rich` with section headers, coloured confidence labels, and file path highlighting
- `README.md` covers: prerequisites, `.env` setup, demo command, sample output
- Full demo run `python investigate.py --repo ../source/pydantic --commit 617abdb1b` completes in < 60 seconds
- The output report matches the manually-written report in all five sections

**Todo List**
- [ ] Implement `renderer.py`:
  - `render_markdown(report, context) -> str` — Markdown with front-matter, five sections, evidence table
  - `save_report(report, context, output_dir) -> Path`
  - `render_terminal(report, context)` — use `rich.console` with panels and coloured labels
- [ ] Add `--output` flag to `investigate.py` (default: `./output`)
- [ ] Write `README.md` with setup, usage, and sample output section
- [ ] End-to-end test: run against `617abdb1b`, verify five sections present, verify `ordered_dict.rs` cited
- [ ] Stretch: run against `deque` commit (`#13757` — find its SHA from HISTORY) to verify tool generalises
- [ ] Update `README.md` with actual sample output from the demo run

**Relevant Context**
- The Markdown report is the primary deliverable — terminal output is secondary
- Confidence label colouring: green = `[documented]`, yellow = `[inferred from code]`, red = `[reconstructed from pattern]`
- The `output/` directory is gitignored; include `output/.gitkeep`
- Report filename: `output/{sha[:8]}-{pr_number}-report.md` (e.g. `output/617abdb1-13824-report.md`)

**Status:** [ ] pending

---

## "Done" Criteria for the MVP

The MVP is complete when all of the following are true:

1. `python investigate.py --repo ../source/pydantic --commit 617abdb1b` completes without error in under 60 seconds
2. A Markdown report is saved to `output/`
3. The report contains all five sections: Change, Before/After, Problem Addressed, Evidence, Confidence/Uncertainty
4. Every claim in the report cites a specific file path or commit SHA that appears in the collected evidence
5. The report distinguishes documented rationale from reconstructed rationale (labels are present)
6. The tool identifies `ordered_dict.rs` as a structural peer of the new `counter.rs`
7. The tool finds the sibling commits `#13505` and `#13757` from HISTORY as context for the `counter` change series
8. The demo can be run by anyone who has cloned the repo and configured `.env`

## Out of Scope

- Web UI or any frontend
- GitHub API (no network access to github.com required)
- Cloning remote repos (user provides a local path)
- Multi-language AST parsing
- Multi-commit / PR-level analysis
- Automated scoring or correctness evaluation
- CI/CD integration
