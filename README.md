# junk

**A reversible legacy-mess obfuscator.** Inflate clean Python source into a
deliberate maintenance nightmare to raise the cost of casual reading and
automated deconstruction — then restore the original *byte-for-byte* with a
single command.

> [中文说明 → README.zh-CN.md](./README.zh-CN.md)

## Why it's safe to be aggressive

junk never reverses the obfuscated code. Before touching anything it writes a
**byte-exact snapshot** of every original file into a local, git-ignored
`.junkmap/` store. `junk restore` copies those bytes straight back. Because
restoration ignores the obfuscated output entirely, transforms can be as
destructive to readability as they like with **zero information loss**.

Two more guarantees keep you out of trouble:

- **AST-level, behaviour-preserving transforms.** Misleading docstrings,
  unreachable dead code, provably-safe local renaming (never parameters,
  globals, closures, or reflection), and order-independent top-level reordering.
- **Double gate + auto-rollback.** After obfuscating, junk recompiles every file
  and (optionally) runs *your* test/bench command. If anything fails, it rolls
  every file back to its clean snapshot automatically.

## Install

```bash
pip install -e .            # core tool
pip install -e '.[redteam]' # also installs the anthropic SDK for `junk redteam`
```

## Usage

```bash
# Safe profile (dead code + misleading comments), default:
junk obfuscate src/

# Everything on, gated by your tests — rolls back if they fail:
junk obfuscate src/ --aggressive --tests "python -m pytest -q"

# See what's currently obfuscated:
junk status

# Put it all back, byte-for-byte:
junk restore
```

### Commands

| Command | What it does |
| --- | --- |
| `obfuscate PATHS [--aggressive] [--tests CMD] [--bench CMD] [--seed N] [--dry-run]` | Snapshot, transform, gate, and (on failure) roll back. |
| `restore [PATHS]` | Restore originals from `.junkmap/` (all managed files if omitted). |
| `status [PATHS]` | Show which files are obfuscated and whether they're intact. |
| `redteam PATHS [--rounds N] [--model ID]` | Use Claude as an anti-reconstruction fitness function to pick the hardest-to-reverse variant, then apply it through the gated path. Needs `ANTHROPIC_API_KEY`. |

## Try it on the example

```bash
junk obfuscate example/sample.py --aggressive --tests "python example/run_checks.py"
junk status
junk restore
# example/sample.py is now identical to what you started with
```

## ⚠️ Keep `.junkmap/` private

The snapshot store is the master key to your original source — anyone who gets
it can reconstruct everything with one `junk restore`. junk adds `.junkmap/` to
`.gitignore` automatically; never commit it or ship it.

## How the pieces fit

```
junk/
  cli.py         # argument parsing + command dispatch
  core.py        # discover -> transform -> snapshot -> gate -> rollback/report
  snapshot.py    # the byte-exact .junkmap/ store
  transforms.py  # AST transforms: dead code, safe rename, top-level reorder
  poison.py      # misleading docstrings (AST) + comments (textual pass)
  gates.py       # compile + test + bench verification
  redteam.py     # Claude-as-fitness seed search
```

## Tests

```bash
python -m pytest -q
```

Covers the three core guarantees: round-trip is byte-identical, a failing gate
auto-rolls-back, and double obfuscation is refused.

## License

MIT — see [LICENSE](./LICENSE).
