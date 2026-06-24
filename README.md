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

## Agent maze mode

The default transforms sprinkle each file with generic stock comments — which an
AI agent cross-referencing the codebase quickly learns to dismiss as noise.
`--narrative` does the opposite: it builds **one fabricated-but-self-consistent
cover story** and renders it into *every* surface — comments, docstrings,
dead-code names, a decoy `ARCHITECTURE.md`, even test names — all keyed to a
shared glossary, so the same entity gets the same fake identity everywhere. An
agent's cross-validation then *confirms* the lie instead of catching it, and it
walks away with a confident-but-wrong account of what your code does. This
attacks the one axis a model can't verify from the code itself: *why*.

```bash
# Render a deterministic, offline cover story across the whole tree:
junk obfuscate src/ --aggressive --narrative template --tests "python -m pytest -q"

# Also rename test_* functions and rewrite README.md into the story:
junk obfuscate src/ --aggressive --narrative template --rename-tests --rewrite-readme
```

The story is written to `.junkmap/narrative.json` (secret — it is part of the
key) and `restore` removes every decoy it created. Behaviour and the gate are
unchanged: narrative mode only changes *what* the poison says, not *how* it is
injected. `--narrative template` is offline and deterministic today;
`--narrative llm` (tailor the story to your real structure with Claude) is
planned.

### Does the maze actually work? — `junk maze-eval`

The honest fitness function. It hands a tool-using agent (`list_files` /
`read_file` / `grep`) the obfuscated tree, measures what it costs (turns, tool
calls, tokens), and — using the clean source in `.junkmap` as ground truth —
checks whether the agent ends up **confidently wrong** or parrots the fake
domain back. `--baseline` reruns on the reconstructed clean tree and reports the
extra cost the maze adds. Needs `ANTHROPIC_API_KEY`.

```bash
junk maze-eval --baseline
```

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

# Agent-maze mode: one self-consistent cover story across every file:
junk obfuscate src/ --aggressive --narrative template --tests "python -m pytest -q"

# See what's currently obfuscated:
junk status

# Put it all back, byte-for-byte:
junk restore
```

### Commands

| Command | What it does |
| --- | --- |
| `obfuscate PATHS [--aggressive] [--narrative off\|template\|llm] [--narrative-theme T] [--rename-tests] [--rewrite-readme] [--tests CMD] [--bench CMD] [--seed N] [--dry-run]` | Snapshot, transform (optionally rendering a self-consistent false narrative), gate, and (on failure) roll back. |
| `restore [PATHS]` | Restore originals from `.junkmap/` (all managed files if omitted); also deletes any decoy docs the narrative created. |
| `status [PATHS]` | Show which files are obfuscated and whether they're intact. |
| `redteam PATHS [--rounds N] [--model ID]` | Use Claude as an anti-reconstruction fitness function to pick the hardest-to-reverse variant, then apply it through the gated path. Needs `ANTHROPIC_API_KEY`. |
| `maze-eval [--task T] [--model ID] [--max-turns N] [--baseline]` | Run a tool-using agent over the obfuscated tree; report its cost (turns/tool-calls/tokens) and whether it's fooled into the cover story. Needs `ANTHROPIC_API_KEY`. |

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
  transforms.py  # AST transforms: dead code, safe rename, reorder, test rename
  poison.py      # misleading docstrings (AST) + comments (textual pass)
  narrative.py   # the cross-file cover story: model, themes, binding, renderers
  gates.py       # compile + test + bench verification
  redteam.py     # Claude-as-fitness seed search
  maze_eval.py   # agent-cost harness: does the maze actually fool an agent?
```

## Tests

```bash
python -m pytest -q
```

Covers the core guarantees (round-trip is byte-identical, a failing gate
auto-rolls-back, double obfuscation is refused) plus the narrative layer:
cross-file/-surface consistency, deterministic binding, decoy-doc deletion on
restore, and the maze-eval harness's offline pieces (sandbox `.junkmap` hiding,
adoption detection).

## License

MIT — see [LICENSE](./LICENSE).
