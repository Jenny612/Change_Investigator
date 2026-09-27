# Change Investigator

A CLI tool that takes a local Git repository and a commit SHA, collects evidence
from the diff, source code, tests, and changelog, and produces a structured
investigation report explaining *why* the change was made.

Evidence is grounded in the repository itself. Every claim in the report is
labelled as `[documented]`, `[inferred from code]`, or `[reconstructed from pattern]`.

---

## Requirements

- Python 3.10+
- Git available on `PATH`
- IBM watsonx credentials (optional — the tool produces a useful evidence-based
  report without them)

---

## Installation

```bash
cd change-investigator
pip install -r requirements.txt
```

---

## Configuration

IBM watsonx synthesis is **optional**. Without credentials the tool collects all
evidence and produces a structured fallback report from that evidence.

To enable LLM synthesis, copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
# then edit .env with your IBM Cloud API key, watsonx URL, and project ID
```

The `.env` file is gitignored and must never be committed.

---

## Usage

```
python investigate.py --repo <path-to-repo> --commit <sha> [--output <output-dir>]
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--repo` | Yes | — | Path to the local Git repository to investigate |
| `--commit` | Yes | — | Commit SHA (full or abbreviated) |
| `--output` | No | `./output` | Directory to write the Markdown report |

---

## Demo (validation case)

The tool was developed and validated against Pydantic commit `617abdb1b`
("Add a `counter` core schema (#13824)").

Assuming the Pydantic repository is checked out alongside this directory:

```bash
python investigate.py --repo ../source/pydantic --commit 617abdb1b
```

The report is saved to `output/617abdb1-13824-report.md`.

---

## What the tool does

```
Phase 1 — Git collection
  Fetches commit metadata, full diff, and surrounding commits.

Phase 2 — Evidence collection
  - Parses the diff into structured file records (source / test / doc / config)
  - Extracts new symbol names from added lines
  - Reads new and modified source files in full
  - Reads test files in full
  - Runs git grep for each extracted symbol across the repo
  - Finds structural peer files (existing files in the same directory with the
    same extension — e.g. ordered_dict.rs when counter.rs is new)
  - Detects sibling commits following the same naming pattern via git log --grep
  - Searches HISTORY.md / CHANGELOG.md for the PR number

Phase 3 — Synthesis
  Assembles all evidence into a grounded prompt and calls IBM watsonx Granite.
  If watsonx is not configured, produces a fallback report directly from the
  collected evidence.

Phase 4 — Rendering
  Saves a Markdown report to output/ and prints a formatted summary to the terminal.
```

---

## Report structure

The report always contains five sections:

1. **Change** — what files and symbols were introduced or modified
2. **Before / After** — the before-state (reconstructed from diff and absence of
   files) versus the after-state
3. **Problem Addressed** — the limitation or gap the change resolves
4. **Evidence** — specific file paths, test assertions, sibling commits, and
   changelog entries that support the findings
5. **Confidence / Uncertainty** — explicit confidence levels for each claim,
   distinguishing `[documented]` from `[inferred from code]` from
   `[reconstructed from pattern]`

---

## Running tests

```bash
python -m pytest
```

Tests that require the Pydantic repository are automatically skipped if
`../source/pydantic` is not present.

---

## Project layout

```
change-investigator/
├── investigate.py          # CLI entry point
├── models.py               # Shared dataclasses
├── config.py               # Credential loading from .env
├── requirements.txt
├── .env.example            # Credential template (safe to commit)
├── collectors/
│   ├── git_collector.py    # git show / log / grep via subprocess
│   ├── source_collector.py # File reads and git grep
│   └── history_collector.py# CHANGELOG search and sibling commit detection
├── analysis/
│   ├── diff_parser.py      # Unified diff → FileDiff objects
│   ├── symbol_extractor.py # New symbols from added lines
│   └── pattern_detector.py # Peer files, before-state, test assertions
├── synthesis/
│   └── llm_synthesiser.py  # Prompt builder, watsonx call, fallback
├── report/
│   └── renderer.py         # Markdown and terminal output
├── tests/                  # pytest test suite
└── output/                 # Generated reports (gitignored)
```
