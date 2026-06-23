"""AST-level, behaviour-preserving obfuscation transforms.

Every transform here is designed to keep program behaviour intact. The double
gate (compile + your test command) plus snapshot-based restore are the safety
net, but these transforms still aim to be correct by construction:

* ``inject_dead_code`` adds only provably-unreachable ``if False:`` blocks.
* ``rename_locals`` renames only function-local bindings that a conservative
  scope analysis proves cannot escape (never parameters, globals, nonlocals,
  imports, names used by nested/closure/comprehension scopes, and never inside
  a function that touches reflection such as ``locals()`` / ``eval``).
* ``reorder_toplevel`` shuffles only contiguous runs of plain top-level function
  definitions whose evaluation is order-independent (no decorators, no
  annotations, constant-only defaults).
"""

from __future__ import annotations

import ast
import random

REFLECTION_NAMES = {
    "locals", "globals", "vars", "eval", "exec", "compile", "__import__",
    "getattr", "setattr", "delattr",
}

_NAME_PREFIXES = [
    "_tmp", "_buf", "_ctx", "_legacy", "_aux", "_scratch", "_acc",
    "_node", "_obj", "_state", "_handle", "_v0", "_q", "_carry",
]
_NAME_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"


def junk_name(rng: random.Random) -> str:
    """Return a plausible-but-meaningless local identifier."""
    suffix = "".join(rng.choice(_NAME_CHARS) for _ in range(6))
    return f"{rng.choice(_NAME_PREFIXES)}_{suffix}"


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


# --------------------------------------------------------------------------- #
# Dead code injection
# --------------------------------------------------------------------------- #

def _make_dead_block(rng: random.Random) -> ast.If:
    """Build an ``if False:`` block full of innocuous, never-run statements."""
    body: list[ast.stmt] = []
    for _ in range(rng.randint(1, 3)):
        target = junk_name(rng)
        value = ast.Constant(rng.randint(0, 9999))
        body.append(ast.Assign(targets=[ast.Name(id=target, ctx=ast.Store())], value=value))
    # An extra harmless mutation for flavour.
    if body and rng.random() < 0.5:
        name = body[0].targets[0].id
        body.append(
            ast.Assign(
                targets=[ast.Name(id=name, ctx=ast.Store())],
                value=ast.BinOp(
                    left=ast.Name(id=name, ctx=ast.Load()),
                    op=ast.Add(),
                    right=ast.Constant(1),
                ),
            )
        )
    return ast.If(test=ast.Constant(False), body=body, orelse=[])


def inject_dead_code(tree: ast.AST, rng: random.Random, density: float = 0.5) -> None:
    """Insert unreachable ``if False:`` blocks into statement bodies in place."""
    targets: list[tuple[list, str]] = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if (
                isinstance(body, list)
                and body
                and all(isinstance(s, ast.stmt) for s in body)
            ):
                targets.append((body, field))

    for body, field in targets:
        if rng.random() >= density:
            continue
        start = 1 if (field == "body" and _is_docstring(body[0])) else 0
        idx = rng.randint(start, len(body))
        body.insert(idx, _make_dead_block(rng))


# --------------------------------------------------------------------------- #
# Provably-safe local renaming
# --------------------------------------------------------------------------- #

def _gather_locals(func) -> set:
    """Return the set of locally-bound names in ``func`` safe to rename.

    Conservative: excludes parameters, ``global``/``nonlocal`` names, imported
    names, and any name that also appears in a nested scope (closure, lambda,
    comprehension, nested def/class). Returns an empty set if the function uses
    reflection, since renaming could then be observable.
    """
    params: set = set()
    a = func.args
    for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs):
        params.add(arg.arg)
    if a.vararg:
        params.add(a.vararg.arg)
    if a.kwarg:
        params.add(a.kwarg.arg)

    assigned: set = set()
    declared: set = set()  # global / nonlocal
    imported: set = set()
    nested: set = set()
    reflection = False

    def add_target(t) -> None:
        if isinstance(t, ast.Name):
            assigned.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                add_target(e)
        elif isinstance(t, ast.Starred):
            add_target(t.value)

    def mark_nested(node) -> None:
        for n in ast.walk(node):
            if isinstance(n, ast.Name):
                nested.add(n.id)
            elif isinstance(n, ast.arg):
                nested.add(n.arg)

    def visit(node) -> None:
        nonlocal reflection
        if isinstance(node, ast.Name) and node.id in REFLECTION_NAMES:
            reflection = True

        if isinstance(node, ast.Lambda):
            mark_nested(node)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            mark_nested(node)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assigned.add(node.name)  # the def name binds in this scope
            mark_nested(node)        # everything inside is a separate scope
            return
        if isinstance(node, ast.Global):
            declared.update(node.names)
            return
        if isinstance(node, ast.Nonlocal):
            declared.update(node.names)
            return
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imported.add(name)
            return
        if isinstance(node, ast.Assign):
            for t in node.targets:
                add_target(t)
            visit(node.value)
            return
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                assigned.add(node.target.id)
            if node.value:
                visit(node.value)
            return
        if isinstance(node, ast.AugAssign):
            add_target(node.target)
            visit(node.value)
            return
        if isinstance(node, (ast.For, ast.AsyncFor)):
            add_target(node.target)
            visit(node.iter)
            for s in node.body:
                visit(s)
            for s in node.orelse:
                visit(s)
            return
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                visit(item.context_expr)
                if item.optional_vars:
                    add_target(item.optional_vars)
            for s in node.body:
                visit(s)
            return
        if isinstance(node, ast.ExceptHandler):
            if node.name:
                assigned.add(node.name)
            if node.type:
                visit(node.type)
            for s in node.body:
                visit(s)
            return
        if isinstance(node, ast.NamedExpr):  # walrus
            if isinstance(node.target, ast.Name):
                assigned.add(node.target.id)
            visit(node.value)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    for stmt in func.body:
        visit(stmt)

    if reflection:
        return set()

    return assigned - params - declared - imported - nested


class _Renamer(ast.NodeTransformer):
    def __init__(self, mapping: dict):
        self.mapping = mapping

    def visit_Name(self, node: ast.Name):  # noqa: N802
        if node.id in self.mapping:
            node.id = self.mapping[node.id]
        return node


def rename_locals(tree: ast.AST, rng: random.Random) -> None:
    """Rename provably-safe function-local bindings throughout ``tree``."""
    for func in [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]:
        candidates = _gather_locals(func)
        if not candidates:
            continue
        used: set = set()
        mapping: dict = {}
        for name in sorted(candidates):
            new = junk_name(rng)
            while new in used:
                new = junk_name(rng)
            used.add(new)
            mapping[name] = new
        renamer = _Renamer(mapping)
        for stmt in func.body:
            renamer.visit(stmt)


# --------------------------------------------------------------------------- #
# Top-level reordering
# --------------------------------------------------------------------------- #

def _reorderable_def(node: ast.stmt) -> bool:
    if not isinstance(node, ast.FunctionDef):
        return False
    if node.decorator_list:
        return False
    if node.returns is not None:
        return False
    a = node.args
    all_args = [*a.posonlyargs, *a.args, *a.kwonlyargs]
    if a.vararg:
        all_args.append(a.vararg)
    if a.kwarg:
        all_args.append(a.kwarg)
    if any(arg.annotation is not None for arg in all_args):
        return False
    defaults = list(a.defaults) + [d for d in a.kw_defaults if d is not None]
    if any(not isinstance(d, ast.Constant) for d in defaults):
        return False
    return True


def reorder_toplevel(tree: ast.Module, rng: random.Random) -> None:
    """Shuffle contiguous runs of order-independent top-level function defs."""
    body = tree.body
    new_body: list[ast.stmt] = []
    i = 0
    n = len(body)
    while i < n:
        if _reorderable_def(body[i]):
            j = i
            run = []
            while j < n and _reorderable_def(body[j]):
                run.append(body[j])
                j += 1
            if len(run) > 1:
                rng.shuffle(run)
            new_body.extend(run)
            i = j
        else:
            new_body.append(body[i])
            i += 1
    tree.body = new_body
