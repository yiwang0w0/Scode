"""Command-line interface for junk."""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Optional, Sequence

from junk import __version__, core, redteam as redteam_mod


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="junk",
        description=(
            "Reversible legacy-mess obfuscator. Inflate clean source into a "
            "maintenance nightmare; restore it byte-for-byte with one command."
        ),
    )
    parser.add_argument("--version", action="version", version=f"junk {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("obfuscate", help="obfuscate files (snapshots originals first)")
    o.add_argument("paths", nargs="+", help="files or directories to obfuscate")
    o.add_argument(
        "--aggressive",
        action="store_true",
        help="enable all transforms (docstring poison, local rename, reorder)",
    )
    o.add_argument("--tests", default=None, help="shell command that must pass post-obfuscation")
    o.add_argument("--bench", default=None, help="optional shell command run as an extra gate")
    o.add_argument("--seed", type=int, default=None, help="deterministic transform seed")
    o.add_argument("--dry-run", action="store_true", help="preview without writing")

    r = sub.add_parser("restore", help="restore originals from the snapshot store")
    r.add_argument("paths", nargs="*", help="files/dirs to restore (default: all managed)")

    s = sub.add_parser("status", help="show which files are currently obfuscated")
    s.add_argument("paths", nargs="*", help="files to inspect (default: all managed)")

    rt = sub.add_parser("redteam", help="use Claude to pick the hardest-to-reverse variant")
    rt.add_argument("paths", nargs="+", help="files or directories to obfuscate")
    rt.add_argument("--rounds", type=int, default=4, help="number of candidate seeds to try")
    rt.add_argument("--model", default=redteam_mod.DEFAULT_MODEL, help="Claude model id")
    rt.add_argument("--tests", default=None, help="shell command that must pass post-obfuscation")
    rt.add_argument("--bench", default=None, help="optional shell command run as an extra gate")
    rt.add_argument("--seed", type=int, default=None, help="base seed for the candidate search")

    return parser


def _do_obfuscate(args, root: Path) -> int:
    seed = args.seed if args.seed is not None else random.randrange(2 ** 31)
    result = core.obfuscate(
        args.paths,
        aggressive=args.aggressive,
        tests=args.tests,
        bench=args.bench,
        seed=seed,
        dry_run=args.dry_run,
        root=root,
    )
    if args.dry_run:
        if not result.ok:
            print("ERROR:", result.reason)
            return 2
        print(f"dry run: would obfuscate {len(result.changed)} file(s) (seed={seed}):")
        for f in result.changed:
            print(f"  {f}")
        return 0
    if result.blocked:
        print("ERROR:", result.reason)
        return 2
    if not result.ok:
        print("gate failed; rolled back to clean.")
        print(result.reason)
        return 1
    print(f"obfuscated {len(result.changed)} file(s) (seed={seed}).")
    print("run `junk restore` to revert. Keep .junkmap/ private and out of git.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = Path.cwd()

    if args.cmd == "obfuscate":
        return _do_obfuscate(args, root)

    if args.cmd == "restore":
        restored = core.restore(args.paths, root=root)
        print(f"restored {len(restored)} file(s).")
        for key in restored:
            print(f"  {key}")
        return 0

    if args.cmd == "status":
        core.print_status(args.paths, root=root)
        return 0

    if args.cmd == "redteam":
        return redteam_mod.redteam(
            args.paths,
            rounds=args.rounds,
            model=args.model,
            tests=args.tests,
            bench=args.bench,
            base_seed=args.seed,
            root=root,
        )

    parser.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
