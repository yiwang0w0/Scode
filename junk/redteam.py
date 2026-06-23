"""Red-team mode: use Claude as an "anti-reconstruction" fitness function.

For each candidate seed, junk generates an aggressive obfuscation of every
target file and asks Claude how confidently it could reconstruct the original
clean intent. The seed whose obfuscation Claude understands *least* wins, and is
then applied through the normal gated ``obfuscate`` path (compile + your tests).

Requires the ``anthropic`` package and an ``ANTHROPIC_API_KEY``. Both are
optional dependencies; the rest of junk works without them.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, Sequence

from junk import core

DEFAULT_MODEL = "claude-opus-4-8"

_SCORE_PROMPT = (
    "You are assessing how resistant a piece of obfuscated Python is to "
    "reverse-engineering. Read the code and estimate, on a scale of 0 to 100, "
    "how confidently you could reconstruct the original clean intent and "
    "structure (0 = impossible, 100 = trivial). Reply with ONLY the integer, "
    "no other text.\n\n```python\n{code}\n```"
)


def _understanding_score(client, model: str, code: str) -> int:
    """Lower is better (harder for Claude to understand)."""
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=32,
            messages=[{"role": "user", "content": _SCORE_PROMPT.format(code=code)}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
        match = re.search(r"\d+", text)
        if not match:
            return 100
        return max(0, min(100, int(match.group())))
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on any API error
        print(f"  (scoring error, treating as max difficulty to avoid: {exc})")
        return 100


def redteam(
    paths: Sequence[str],
    rounds: int = 4,
    model: str = DEFAULT_MODEL,
    tests: Optional[str] = None,
    bench: Optional[str] = None,
    base_seed: Optional[int] = None,
    root: Optional[Path] = None,
) -> int:
    """Search seeds for the obfuscation Claude understands least, then apply it."""
    try:
        import anthropic
    except ImportError:
        print("redteam requires the 'anthropic' package: pip install 'junk[redteam]'")
        return 1

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("redteam requires the ANTHROPIC_API_KEY environment variable.")
        return 1

    root = Path(root or Path.cwd()).resolve()
    client = anthropic.Anthropic()

    files = core.discover_py_files(paths, root)
    if not files:
        print("no .py files found in the given paths.")
        return 1

    from junk.snapshot import SnapshotStore

    store = SnapshotStore(root)
    already = [str(f) for f in files if store.is_obfuscated(f)]
    if already:
        print("already obfuscated (run `junk restore` first):")
        for f in already:
            print(f"  {f}")
        return 2

    if base_seed is None:
        base_seed = 0

    best_seed = None
    best_score = None
    for r in range(rounds):
        seed = base_seed + r
        total = 0
        valid = True
        for f in files:
            src = f.read_text(encoding="utf-8")
            try:
                obf = core.transform_source(src, aggressive=True, seed=f"{seed}:{store.key_for(f)}")
            except SyntaxError as exc:
                print(f"  cannot parse {f}: {exc}")
                valid = False
                break
            total += _understanding_score(client, model, obf)
        if not valid:
            continue
        avg = total / len(files)
        print(f"seed {seed}: mean reconstruction confidence {avg:.1f}/100")
        if best_score is None or avg < best_score:
            best_score, best_seed = avg, seed

    if best_seed is None:
        print("no viable obfuscation found.")
        return 1

    print(f"\napplying best seed {best_seed} (confidence {best_score:.1f}/100)...")
    result = core.obfuscate(
        paths,
        aggressive=True,
        tests=tests,
        bench=bench,
        seed=best_seed,
        root=root,
    )
    if result.blocked:
        print("ERROR:", result.reason)
        return 2
    if not result.ok:
        print("gate failed; rolled back to clean.")
        print(result.reason)
        return 1
    print(f"obfuscated {len(result.changed)} file(s). `junk restore` reverts them.")
    return 0
