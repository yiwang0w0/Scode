"""Orchestration: discover, transform, gate, snapshot, restore, report.

This module wires the snapshot store, the AST transforms, the textual poison
pass, and the verification gates into the four user-facing operations.
"""

from __future__ import annotations

import ast
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from junk import gates, poison, transforms
from junk.snapshot import (
    JUNKMAP_DIR,
    SnapshotStore,
    ensure_gitignore,
    sha256_bytes,
)


@dataclass
class ObfuscateResult:
    ok: bool
    reason: str = ""
    changed: List[str] = field(default_factory=list)
    rolled_back: bool = False
    blocked: bool = False


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #

def discover_py_files(paths: Sequence[str], root: Path) -> List[Path]:
    """Expand ``paths`` (files or directories) into a list of .py files."""
    root = Path(root).resolve()
    found: List[Path] = []
    for raw in paths:
        p = Path(raw)
        if not p.is_absolute():
            p = root / p
        p = p.resolve()
        if p.is_dir():
            for f in sorted(p.rglob("*.py")):
                if JUNKMAP_DIR in f.parts:
                    continue
                found.append(f.resolve())
        elif p.suffix == ".py":
            found.append(p)

    seen: set = set()
    ordered: List[Path] = []
    for f in found:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    return ordered


# --------------------------------------------------------------------------- #
# Transformation
# --------------------------------------------------------------------------- #

def transform_source(source: str, aggressive: bool, seed) -> str:
    """Return an obfuscated rendering of ``source``.

    Safe profile (default): unreachable dead code + misleading comments.
    Aggressive: also docstring poisoning, provably-safe local renaming, and
    top-level reordering, with a denser comment pass.
    """
    rng = random.Random(seed)
    tree = ast.parse(source)

    if aggressive:
        poison.poison_docstrings(tree, rng)
        transforms.rename_locals(tree, rng)
        transforms.reorder_toplevel(tree, rng)

    transforms.inject_dead_code(tree, rng)
    ast.fix_missing_locations(tree)
    rendered = ast.unparse(tree)

    rendered = poison.inject_comments(rendered, rng, density=0.5 if aggressive else 0.25)
    return rendered


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #

def is_obfuscated(path, root: Optional[Path] = None) -> bool:
    store = SnapshotStore(Path(root or Path.cwd()))
    return store.is_obfuscated(path)


def obfuscate(
    paths: Sequence[str],
    aggressive: bool = False,
    tests: Optional[str] = None,
    bench: Optional[str] = None,
    seed=None,
    dry_run: bool = False,
    root: Optional[Path] = None,
) -> ObfuscateResult:
    """Obfuscate files, gate the result, and roll back on failure."""
    root = Path(root or Path.cwd()).resolve()
    store = SnapshotStore(root)
    files = discover_py_files(paths, root)

    if not files:
        return ObfuscateResult(ok=False, reason="no .py files found in the given paths")

    # Refuse to obfuscate anything already under management: snapshotting an
    # already-obfuscated file would capture the garbage as the "original" and
    # destroy reversibility.
    already = [str(f) for f in files if store.is_obfuscated(f)]
    if already:
        listing = "\n  ".join(already)
        return ObfuscateResult(
            ok=False,
            blocked=True,
            reason=(
                "already obfuscated (run `junk restore` first):\n  " + listing
            ),
        )

    if seed is None:
        seed = random.randrange(2 ** 31)

    # Pre-validate every file parses before we touch anything.
    planned = []
    for f in files:
        src = f.read_text(encoding="utf-8")
        try:
            new = transform_source(src, aggressive, f"{seed}:{store.key_for(f)}")
        except SyntaxError as exc:
            return ObfuscateResult(ok=False, reason=f"cannot parse {f}: {exc}")
        planned.append((f, new))

    if dry_run:
        return ObfuscateResult(
            ok=True,
            reason="dry run",
            changed=[str(f) for f, _ in planned],
        )

    ensure_gitignore(root)

    snapped: List[Path] = []
    for f, new in planned:
        store.snapshot(f)
        snapped.append(f)
        f.write_text(new, encoding="utf-8")

    ok, msg = gates.run_gates(files, tests, bench, root)
    if not ok:
        for f in snapped:
            store.restore(f)
        return ObfuscateResult(ok=False, reason=msg, rolled_back=True)

    for f in snapped:
        store.mark_obfuscated(f, sha256_bytes(f.read_bytes()))

    return ObfuscateResult(ok=True, reason=msg, changed=[str(f) for f in snapped])


def restore(paths: Sequence[str], root: Optional[Path] = None) -> List[str]:
    """Restore the original bytes of managed files. Empty ``paths`` = all."""
    root = Path(root or Path.cwd()).resolve()
    store = SnapshotStore(root)

    if paths:
        keys = []
        for raw in paths:
            p = Path(raw)
            if not p.is_absolute():
                p = root / p
            if p.resolve().is_dir():
                prefix = p.resolve().relative_to(root).as_posix()
                keys += [k for k in store.entries() if k == prefix or k.startswith(prefix + "/")]
            else:
                keys.append(store.key_for(p))
    else:
        keys = list(store.entries().keys())

    restored: List[str] = []
    for key in keys:
        if store.restore_key(key):
            restored.append(key)
    return restored


def status(paths: Sequence[str], root: Optional[Path] = None) -> List[dict]:
    """Return the management status of files (all managed files if empty)."""
    root = Path(root or Path.cwd()).resolve()
    store = SnapshotStore(root)
    entries = store.entries()

    if paths:
        wanted = {store.key_for(p) for p in paths}
        entries = {k: v for k, v in entries.items() if k in wanted}

    rows: List[dict] = []
    for key, entry in sorted(entries.items()):
        target = root / key
        current_sha = sha256_bytes(target.read_bytes()) if target.exists() else None
        rows.append(
            {
                "path": key,
                "obfuscated": True,
                "original_sha256": entry["original_sha256"],
                "current_sha256": current_sha,
                "intact": current_sha == entry.get("obfuscated_sha256"),
            }
        )
    return rows


def print_status(paths: Sequence[str], root: Optional[Path] = None) -> None:
    rows = status(paths, root)
    if not rows:
        print("no files are currently obfuscated.")
        return
    print(f"{'STATUS':<12} {'INTACT':<7} PATH")
    for row in rows:
        intact = "yes" if row["intact"] else "MODIFIED"
        print(f"{'obfuscated':<12} {intact:<7} {row['path']}")
    print(f"\n{len(rows)} file(s) under management. `junk restore` reverts them.")
