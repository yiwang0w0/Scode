"""Misleading-comment and docstring "poisoning".

Docstrings are real AST nodes, so they are swapped at the AST level. Line
comments cannot survive ``ast.unparse`` (it drops them), so they are injected as
a final textual pass: the generated source is re-parsed, statement start lines
are located, and standalone comment lines are spliced in at matching
indentation. Because comments only ever land on statement boundaries and never
inside a literal, they are behaviour-preserving and the compile gate validates
the result regardless.

When a :class:`~junk.narrative.Narrative` is supplied, every comment/docstring is
*rendered from the shared cover story* (keyed by the entity it sits on) instead
of being a random pick from the flat fallback lists, so the lie is consistent
across files. With ``narrative=None`` the behaviour is exactly the legacy flat
random pass.
"""

from __future__ import annotations

import ast
import random

from junk.narrative import (
    render_comment,
    render_docstring,
    render_module_docstring,
)

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


def _set_docstring(node: ast.AST, text: str) -> None:
    body = getattr(node, "body", None)
    if not isinstance(body, list):
        return
    doc = ast.Expr(value=ast.Constant(text))
    if body and _is_docstring(body[0]):
        body[0] = doc
    else:
        body.insert(0, doc)


def iter_scopes(tree: ast.AST, base: str):
    """Yield ``(node, entity_key)`` for every def/class, dotted-qualname keyed.

    ``entity_key`` is ``"<base>::<dotted.qualname>"`` so the same entity gets the
    same narrative binding across surfaces and files.
    """
    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}.{child.name}" if prefix else child.name
                yield child, f"{base}::{qual}"
                yield from walk(child, qual)
            else:
                yield from walk(child, prefix)

    yield from walk(tree, "")


def poison_docstrings(tree, rng: random.Random, narrative=None, base=None) -> None:
    """Replace or insert misleading docstrings on the module and definitions."""
    if narrative is None:
        scopes = [tree]
        scopes += [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        for node in scopes:
            _set_docstring(node, rng.choice(MISLEADING_DOCSTRINGS))
        return

    _set_docstring(tree, render_module_docstring(narrative, base, rng))
    for node, key in iter_scopes(tree, base):
        _set_docstring(node, render_docstring(narrative, narrative.bind(key), rng))


def _scope_ranges(tree: ast.AST, base: str):
    ranges = []
    for node, key in iter_scopes(tree, base):
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", start)
        if start is not None:
            ranges.append((start, end, key))
    return ranges


def _resolve_key(ranges, lineno: int, base: str) -> str:
    """Innermost scope whose line range contains ``lineno`` (else the module)."""
    best = None
    for start, end, key in ranges:
        if start <= lineno <= end:
            span = end - start
            if best is None or span < best[0]:
                best = (span, key)
    return best[1] if best else f"{base}::<module>"


def inject_comments(
    source: str,
    rng: random.Random,
    density: float = 0.25,
    narrative=None,
    base=None,
) -> str:
    """Splice misleading standalone comment lines before random statements."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    ranges = _scope_ranges(tree, base) if narrative is not None else None
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
        if narrative is not None:
            key = _resolve_key(ranges, lineno, base)
            text = render_comment(narrative, narrative.bind(key), rng)
        else:
            text = rng.choice(MISLEADING_COMMENTS)
        insertions.setdefault(lineno, []).append(f"{indent}# {text}")

    if not insertions:
        return source

    out: list[str] = []
    for i, line in enumerate(lines, start=1):
        if i in insertions:
            out.extend(insertions[i])
        out.append(line)
    return "\n".join(out)
