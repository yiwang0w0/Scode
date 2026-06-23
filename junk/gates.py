"""Verification gates run after obfuscation.

If any gate fails, the caller rolls every touched file back to its clean
snapshot. The compile gate always runs; the test and bench gates run only when
the corresponding command is supplied.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional, Sequence, Tuple


def compile_file(path) -> Tuple[bool, str]:
    """Smoke-test that a file still compiles to bytecode."""
    p = Path(path)
    try:
        compile(p.read_text(encoding="utf-8"), str(p), "exec")
        return True, ""
    except SyntaxError as exc:
        return False, f"{p}: {exc}"


def run_command(cmd: str, cwd) -> Tuple[bool, str]:
    """Run a shell command in ``cwd``; success is exit code 0."""
    proc = subprocess.run(
        cmd,
        shell=True,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def run_gates(
    files: Sequence[Path],
    tests: Optional[str],
    bench: Optional[str],
    cwd,
) -> Tuple[bool, str]:
    """Run all configured gates. Returns ``(ok, message)``."""
    for f in files:
        ok, msg = compile_file(f)
        if not ok:
            return False, f"compile gate failed:\n{msg}"

    if tests:
        ok, out = run_command(tests, cwd)
        if not ok:
            return False, f"test gate failed (`{tests}`):\n{out.strip()}"

    if bench:
        ok, out = run_command(bench, cwd)
        if not ok:
            return False, f"bench gate failed (`{bench}`):\n{out.strip()}"

    return True, "all gates passed"
