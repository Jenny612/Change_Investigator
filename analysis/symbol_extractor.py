"""Symbol extractor — finds new names introduced by a commit's added lines."""

from __future__ import annotations

import re
from models import FileDiff


# ---------------------------------------------------------------------------
# Per-language patterns
# ---------------------------------------------------------------------------

# Python: class Foo, def foo, FOO = ...
_PY_PATTERNS = [
    re.compile(r"^class\s+([A-Z][A-Za-z0-9_]*)"),          # class CounterSchema
    re.compile(r"^def\s+([a-z_][A-Za-z0-9_]*)"),            # def counter_schema
    re.compile(r"^([A-Z_]{2,})\s*[:=]"),                     # COUNTER_TYPE = ...
    re.compile(r"['\"]([a-z][a-z0-9_-]{2,})['\"]"),         # 'counter', "ordered-dict"
]

# Rust: pub struct Foo, fn foo, const FOO, impl Foo
_RS_PATTERNS = [
    re.compile(r"pub\s+struct\s+([A-Z][A-Za-z0-9_]*)"),     # pub struct CounterValidator
    re.compile(r"pub\s+fn\s+([a-z_][A-Za-z0-9_]*)"),        # pub fn get_counter_type
    re.compile(r"fn\s+([a-z_][A-Za-z0-9_]*)"),              # fn consume_iterator
    re.compile(r"const\s+([A-Z_]{2,})\s*:"),                 # const FOO: &str
    re.compile(r"impl\s+(?:BuildValidator|Validator|TypeSerializer|BuildSerializer)\s+for\s+([A-Z][A-Za-z0-9_]*)"),
    re.compile(r"EXPECTED_TYPE.*['\"]([a-z][a-z0-9_-]+)['\"]"),  # "counter", "ordered-dict"
    re.compile(r"([A-Z][a-z]+(?:[A-Z][a-z]+)+)\("),          # CounterValidator(
]

_GENERIC_PATTERNS = [
    re.compile(r"['\"]([a-z][a-z0-9_-]{3,})['\"]"),         # any quoted lowercase identifier
]


def extract_new_symbols(diffs: list[FileDiff], max_per_file: int = 20) -> list[str]:
    """Return a deduplicated list of new symbol names from added lines in *diffs*.

    Focuses on symbols that are likely to be grep-worthy (class names, function names,
    schema type strings).
    """
    seen: set[str] = set()
    result: list[str] = []

    # Common noise words to skip
    _SKIP = {
        "self", "true", "false", "none", "type", "str", "int", "bool", "any",
        "dict", "list", "set", "float", "bytes", "use", "let", "mut", "pub",
        "mod", "impl", "for", "fn", "struct", "enum", "match", "return", "if",
        "else", "while", "loop", "in", "as", "where", "from", "import", "def",
        "class", "with", "pass", "raise", "try", "except", "finally", "yield",
        "not", "and", "or", "is", "not", "del", "global", "nonlocal", "assert",
        "break", "continue", "lambda", "async", "await", "None", "True", "False",
        "super", "static", "new", "const", "move", "ref", "box", "dyn", "crate",
    }

    def _add(sym: str) -> None:
        sym = sym.strip()
        if sym and sym.lower() not in _SKIP and len(sym) > 2 and sym not in seen:
            seen.add(sym)
            result.append(sym)

    for diff in diffs:
        count = 0
        patterns = _RS_PATTERNS if diff.language == "rust" else _PY_PATTERNS
        for line in diff.added_lines:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            for pat in patterns:
                for m in pat.finditer(line):
                    _add(m.group(1))
                    count += 1
                    if count >= max_per_file:
                        break
                if count >= max_per_file:
                    break
            if count >= max_per_file:
                break

    return result


def prioritise_symbols(symbols: list[str]) -> list[str]:
    """Put the most grep-worthy symbols first.

    Heuristic: CamelCase class names and lowercase schema type strings first.
    """
    camel = [s for s in symbols if re.match(r"^[A-Z][A-Za-z]{4,}$", s)]
    schema_strings = [s for s in symbols if re.match(r"^[a-z][a-z0-9-]{3,}$", s)]
    rest = [s for s in symbols if s not in camel and s not in schema_strings]
    return camel + schema_strings + rest
