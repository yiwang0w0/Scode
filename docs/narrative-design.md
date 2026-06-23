# Design: cross-file self-consistent false narrative ("Agent maze" mode)

Status: **v1 template mode implemented** (comments/docstrings/dead-code/doc-overlay/test-rename;
LLM mode + public-symbol rename still pending) · Target: `junk` v0.2 · Author: design session 2026-06-23

## 1. Motivation — today's poison is *anti*-consistent

`core.transform_source()` runs **per file, statelessly** (each file gets its own
`f"{seed}:{key}"` RNG). The poison passes (`poison.poison_docstrings`,
`poison.inject_comments`) draw every string from the same two flat lists with
`rng.choice(...)`. Consequence: every file is sprinkled with the *same ~24 generic
quips*, uncorrelated with each other or with the code.

Against a human skimmer that is mild friction. Against an **agent that
cross-references files**, it is a *tell*: after two or three files the agent
learns "these comments are boilerplate noise" and discounts the entire channel.
The poison defeats itself.

The fix inverts the property. Instead of many independent random lies, emit **one
fabricated-but-internally-coherent cover story**, and render *every* surface from
it. Now the agent's cross-validation — the very thing that caught the old noise —
**confirms** the lie, because the lie agrees with itself across files, comments,
docstrings, dead code, docs, and tests. The attack lands on the one axis an agent
cannot verify from the code itself: **business intent / *why***.

## 2. Goals & non-goals

**v1 surfaces (all narrative-driven):**
- comments + docstrings
- dead-code naming + lore (decoy "subsystems")
- README / docs overlay (generated decoy doc; optional rewrite of an existing one)
- test names + test docstrings (identifiers and prose only — never assertions)

**v1 generation:** template mode (offline, deterministic, unit-testable) first.
LLM mode fills the *same* data model later.

**Default plausibility posture:** *loose coupling* (claims attach to the
unverifiable why; never contradict visibly obvious operations). Tight coupling is
an opt-in.

**Deferred to v2:**
- public-symbol renaming aligned to the glossary (touches behaviour + cross-file
  references; current tool deliberately renames only locals and never params /
  public names — keep that invariant for now)
- reference-web / fake-call-graph indirection
- name *collision* mode for grep pollution

**Unchanged invariants:**
- Reversibility is snapshot-based; transforms may be arbitrarily nasty.
- The double gate (compile + `--tests` [+ `--bench`]) must stay green. The
  narrative changes the *content* of poison, never its *mechanism*, so the safety
  model is untouched.
- `.junkmap/` is the master key and never ships. The narrative artifact lives
  there and is equally secret.

## 3. The Narrative artifact

One obfuscation run = one `Narrative`, built **once** over the whole file set and
persisted at `.junkmap/narrative.json` (already git-ignored).

```jsonc
{
  "version": 1,
  "seed": 1234,
  "mode": "template",
  "domain": "distributed market-data settlement pipeline",   // single false premise
  "subsystems": ["broker feed", "reconciliation engine", "audit ledger"],
  "incidents": [
    { "id": "INC-2019-0420", "blurb": "double-settlement under venue failover" }
  ],
  "lore": [
    "the reconciliation engine must flush before the audit ledger",
    "checkpoints are sharded by venue id"
  ],
  "glossary": {
    // entity_key -> bound fake concept. entity_key = "<relpath>::<qualname>"
    "junk/core.py::obfuscate":        { "concept": "settlement_reconcile", "subsystem": "reconciliation engine", "incident": "INC-2019-0420" },
    "junk/snapshot.py::SnapshotStore":{ "concept": "ledger_checkpoint_store", "subsystem": "audit ledger" },
    "junk/gates.py::run_gates":       { "concept": "risk_circuit_breaker", "subsystem": "reconciliation engine" }
  }
}
```

`glossary` is the **single source of truth**. No surface invents text on its own;
every surface *renders* from a bound glossary entry plus shared `lore`/`incidents`.

### Stable binding

`entity_key` = `"<relpath>::<qualname>"` (module-level entities use `<relpath>`).
Binding is `concept = pick(theme.vocab, hash(seed, entity_key))`, so the **same
entity always maps to the same fake concept across every file and surface**. This
is the mechanical root of cross-file consistency.

## 4. Architecture change — build-once, thread-through

The only structural change to the pipeline:

```python
# core.obfuscate()
files = discover_py_files(paths, root)
narrative = build_narrative(files, seed, mode, root)   # reads/writes .junkmap/narrative.json
for f, _ in planned:
    new = transform_source(src, aggressive, seed,
                           narrative=narrative,
                           entity_key_base=store.key_for(f))
apply_doc_overlay(narrative, root, store)              # surface C
```

- `transform_source` gains `narrative` + the file's key base; passes them into the
  poison/dead-code passes.
- `poison.*` stop calling `rng.choice(FLAT_LIST)` and call
  `render_comment(narrative, entry, lore)` / `render_docstring(...)`.
- Test files are ordinary `.py` members of the set; the test-name pass activates
  when the module path matches a test pattern (`tests/`, `test_*.py`).

`build_narrative` is mode-dispatched and **idempotent**: if a valid
`narrative.json` exists for this `seed`, reuse it (unless `--refresh-narrative`).
Template mode is pure-deterministic; LLM mode caches its result so subsequent
transforms are deterministic given the artifact.

## 5. Per-surface rendering specs

### A. Comments & docstrings (mechanism unchanged, content from glossary)
- `poison_docstrings`: module → domain-level docstring; each func/class → its bound
  concept's role docstring (loose: role, ordering, incident refs — never a claim
  the visible body obviously contradicts).
- `inject_comments`: same textual splice; comment text references the entity's
  bound concept + a shared `lore`/`incident` item.
- Gate-safe: docstrings are string literals; comments never execute. (Swapping
  `__doc__` is already done under `--aggressive` today, so the rare
  doc-introspecting program is a pre-existing, gate-covered risk.)

### B. Dead-code naming + lore
- Extend `inject_dead_code`: dead vars/funcs are named after subsystems/concepts
  (not random `junk_name`), and their comments cite the same incident ids /
  invariants used elsewhere — so a decoy reads as a real, load-bearing subsystem.
- Optional decoy top-level functions (e.g. `_incident_4420_workaround`) referenced
  **only** from opaque-false branches, so static reachability looks murky while the
  runtime never enters them.
- Gate-safe: everything stays under `if False:` / never-called. The opaque-false
  predicate must be *genuinely* false at runtime (compile + import + tests never
  enter it), or the gate rolls it back.

### C. README / docs overlay
- **Default (safe): generate a decoy doc** — e.g. `ARCHITECTURE.md` or
  `docs/<subsystem>.md` describing the fake domain, consistent with the glossary.
  Tracked as a **"created" snapshot entry** → restore *deletes* it (see §6).
- **Opt-in (`--rewrite-readme`): rewrite an existing README** to the fake domain.
  Its original bytes are snapshotted → restore writes them back. Off by default;
  overwriting the user's real README is invasive.

### D. Test names + test docstrings
- Rename `test_*` function identifiers to narrative vocabulary, **keeping the
  `test_` prefix** (so pytest still discovers them) and avoiding collisions; inject
  narrative docstrings.
- **Never touch assertions or any executable line** — only the identifier and
  prose. Tests still exercise the real behaviour and stay green.
- Caveat: if the user's CI pins exact test node-ids, renaming breaks it → renaming
  is gated behind `--rename-tests`; docstring-only injection is the default for the
  test surface.

## 6. Snapshot / restore extensions

`SnapshotStore` is already byte-based and path-agnostic, so snapshotting and
restoring existing non-`.py` files (README, tests) needs **no change** — only the
*discovery* of those paths. Two additions are required:

1. **"created" entries** for generated decoy files. Manifest entry gains
   `"created": true` with no blob. `restore_key` branches:
   - normal entry → write original bytes back (today's behaviour)
   - created entry → `target.unlink(missing_ok=True)` and drop the entry
2. **Broader discovery** for surface C/D targets: a `discover_targets()` that
   yields the `.py` set (unchanged) plus any doc files the overlay will touch, and
   registers the decoy-doc path to be created.

On full `restore`, also clear `narrative.json` (it is run-scoped state). Keep it on
partial restores so an incremental re-obfuscate reuses the same story.

## 7. Generation modes (same data model)

- **template** (v1, no API): `themes/` holds N pre-authored themes, each a
  `{domain, subsystems, incidents, lore, vocab}` skeleton. `--seed` picks the
  theme and drives all binding. Fully offline, deterministic, unit-testable.
- **llm** (later): feed Claude the **structural skeleton** (module list, public
  symbols, call edges — not necessarily bodies) and have it invent one coherent
  domain + a glossary covering every entity + lore/incidents, returned as JSON that
  validates against the `Narrative` schema. Reuse `redteam`'s `anthropic` client
  and `--model`. Tight coupling (feed real bodies, craft a locally-consistent false
  intent) is an additional opt-in here.

Both paths produce the **identical** `Narrative` object; everything downstream is
mode-agnostic.

## 8. CLI surface

```
--narrative {off,template,llm}   # default off; `template` is the v1 maze profile
--narrative-theme NAME           # pin a template theme (else seed-chosen)
--refresh-narrative              # regenerate the cached artifact (llm)
--rewrite-readme                 # surface C sub-mode 2 (off by default)
--rename-tests                   # surface D identifier rename (off by default)
```
Reuses existing `--seed`, `--model`. A future `--maze` umbrella can bundle the
recommended defaults.

## 9. Consistency checklist (what "self-consistent" means, concretely)

The same `INC-2019-0420` must appear, in agreement, across:
- a docstring on `obfuscate` ("...mitigated after INC-2019-0420"),
- an injected comment near a call site,
- a dead-code function `_incident_4420_workaround`,
- a line in the generated `ARCHITECTURE.md` changelog,
- a renamed test `test_settlement_reconcile_after_0420`.

If a fact is referenced anywhere, it is rendered from `incidents`/`lore`, never
free-typed — that is the property the generator must guarantee.

## 10. Relationship to the agent-cost harness (path A)

This generator is the *thing under test* for the future harness. The harness's
"agent terminates **confidently wrong**" rate is the direct fitness signal for
narrative quality (did the agent adopt the fake domain?). Build the narrative now
(B); measure and tune it with the harness later (A).

## 11. Open questions

- Theme authorship: hand-write a few strong themes, or generate-then-freeze a
  library with the LLM once and ship them as templates?
- Decoy-doc placement: a single top-level `ARCHITECTURE.md`, or several
  `docs/<subsystem>.md` for more cross-file surface?
- How aggressively should dead-code indirection feign reachability before it risks
  confusing the gate's reachability assumptions?
