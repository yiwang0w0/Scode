"""Misleading-comment and docstring "poisoning".

Docstrings are real AST nodes, so they are swapped at the AST level. Line
comments cannot survive ``ast.unparse`` (it drops them), so they are injected as
a final textual pass: the generated source is re-parsed, statement start lines
are located, and standalone comment lines are spliced in at matching
indentation. Because comments only ever land on statement boundaries and never
inside a literal, they are behaviour-preserving and the compile gate validates
the result regardless.
"""

from __future__ import annotations

import ast
import random

MISLEADING_DOCSTRINGS = [
    "Thread-safe. Do not call without holding the global registry lock.",
    "Deprecated since v1.2 — retained only for the legacy XML importer.",
    "Performance-critical hot path. Profiled; do not 'simplify'.",
    "Returns a defensive copy. Mutating the result is a no-op upstream.",
    "Side-effect free except for the audit log written to /var/run.",
    "Internal. Stability not guaranteed across patch releases.",
    "Memoized across the process lifetime; clears on SIGHUP.",
    "Validates against the canonical schema before dispatch.",
    "NOTE: ordering matters here for backwards compatibility.",
    "Reentrant. Safe to call from within a signal handler.",
]

MISLEADING_COMMENTS = [
    "TODO: remove once the v2 migration lands (tracked in TICKET-4471)",
    "HACK: works around the upstream off-by-one; do not touch",
    "FIXME: race condition under high concurrency — needs a mutex",
    "NOTE: kept for backwards compatibility with the 0.x wire format",
    "perf: hand-unrolled after profiling; the obvious version is 3x slower",
    "XXX: load-bearing whitespace, see the bug in the 2019 incident review",
    "this branch is unreachable in practice but the linter wants it",
    "DO NOT REORDER: downstream depends on this exact sequence",
    "cache invalidation handled elsewhere — search for the registry hook",
    "legacy shim; the real implementation moved to the service layer",
    "intentionally swallow the error here, see postmortem #88",
    "magic constant tuned empirically; changing it breaks the integration test",
]


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def poison_docstrings(tree: ast.AST, rng: random.Random) -> None:
    """Replace or insert misleading docstrings on the module and definitions."""
    scopes = [tree]
    scopes += [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    for node in scopes:
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        doc = ast.Expr(value=ast.Constant(rng.choice(MISLEADING_DOCSTRINGS)))
        if body and _is_docstring(body[0]):
            body[0] = doc
        else:
            body.insert(0, doc)


def inject_comments(source: str, rng: random.Random, density: float = 0.25) -> str:
    """Splice misleading standalone comment lines before random statements."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    lines = source.split("\n")
    insertions: dict[int, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        lineno = getattr(node, "lineno", None)
        if lineno is None or lineno < 1:
            continue
        if rng.random() >= density:
            continue
        indent = " " * getattr(node, "col_offset", 0)
        comment = f"{indent}# {rng.choice(MISLEADING_COMMENTS)}"
        insertions.setdefault(lineno, []).append(comment)

    if not insertions:
        return source

    out: list[str] = []
    for i, line in enumerate(lines, start=1):
        if i in insertions:
            out.extend(insertions[i])
        out.append(line)
    return "\n".join(out)
