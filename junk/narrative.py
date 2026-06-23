"""Cross-file self-consistent false narrative ("Agent maze" mode).

A single fabricated-but-coherent *cover story* is built once per obfuscation run
and rendered into every surface (comments, docstrings, dead code, docs, tests),
so an agent cross-referencing the codebase finds the lie **agreeing with itself**
instead of catching random noise. See ``docs/narrative-design.md``.

This module is the offline, deterministic core:

* the :class:`Narrative` data model + JSON persistence,
* the built-in template :data:`THEMES`,
* deterministic ``entity_key -> concept`` binding (the root of cross-file
  consistency),
* the text renderers every surface draws from.

The LLM generator is a second *filler for the same data model* and is added
later; everything downstream of :func:`build_narrative` is mode-agnostic.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from junk.snapshot import JUNKMAP_DIR

SCHEMA_VERSION = 1
NARRATIVE_NAME = "narrative.json"
MODES = ("off", "template", "llm")


# --------------------------------------------------------------------------- #
# Built-in template themes
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Theme:
    name: str
    domain: str
    subsystems: List[str]
    vocab: List[str]            # fake "concept" base names entities bind to
    lore: List[str]            # cross-referencing invariants
    incident_blurbs: List[str]  # one-liners; stable ids are minted per run


THEMES: Dict[str, Theme] = {
    "settlement": Theme(
        name="settlement",
        domain="distributed market-data settlement pipeline",
        subsystems=[
            "broker feed", "reconciliation engine", "audit ledger",
            "venue gateway", "settlement clearinghouse",
        ],
        vocab=[
            "settlement_reconcile", "ledger_checkpoint", "venue_dispatch",
            "clearing_window", "trade_netting", "position_rollup", "margin_sweep",
            "fill_aggregator", "book_snapshot", "risk_circuit_breaker",
            "fixings_cache", "settlement_cycle", "nostro_balance",
            "tick_normalizer", "venue_failover",
        ],
        lore=[
            "the reconciliation engine must flush before the audit ledger",
            "checkpoints are sharded by venue id",
            "settlement runs in T+2 windows aligned to the clearing calendar",
            "every fill is netted against the open position before rollup",
            "the venue gateway replays from the last checkpoint on reconnect",
            "margin is swept at the close of each clearing window",
        ],
        incident_blurbs=[
            "double-settlement under venue failover",
            "off-by-one in the T+2 clearing window",
            "checkpoint corruption during a venue reconnect storm",
            "race between margin sweep and position rollup",
            "stale fixings cache served after a SIGHUP",
        ],
    ),
    "telemetry": Theme(
        name="telemetry",
        domain="real-time fleet telemetry ingestion and control plane",
        subsystems=[
            "edge collector", "ingestion gateway", "stream router",
            "control plane", "cold-storage archiver", "alerting fabric",
        ],
        vocab=[
            "telemetry_ingest", "edge_collector", "stream_partition",
            "control_lease", "heartbeat_reaper", "backpressure_valve",
            "shard_rebalance", "cold_archive_flush", "alert_debounce",
            "fleet_registry", "watermark_tracker", "replay_cursor",
            "sensor_fusion", "quota_governor", "lease_renew",
        ],
        lore=[
            "the control plane must renew its lease before the heartbeat reaper fires",
            "streams are partitioned by fleet id",
            "backpressure opens the valve before the ingestion gateway drops frames",
            "cold-storage flushes lag the live watermark by one epoch",
            "the stream router rebalances shards on every membership change",
            "alerts are debounced across a rolling epoch window",
        ],
        incident_blurbs=[
            "lease expiry storm collapsed the control plane",
            "watermark skew dropped a partition's frames",
            "shard rebalance thrash under fleet churn",
            "alert storm from a debounce window misfire",
            "replay cursor rewound past the cold-archive boundary",
        ],
    ),
}


# --------------------------------------------------------------------------- #
# Stable hashing — process-independent (NOT Python's salted hash())
# --------------------------------------------------------------------------- #

def _h(seed: int, *parts: str) -> int:
    raw = f"{seed}\x00" + "\x00".join(parts)
    return int.from_bytes(hashlib.sha256(raw.encode("utf-8")).digest()[:8], "big")


# --------------------------------------------------------------------------- #
# The narrative artifact
# --------------------------------------------------------------------------- #

@dataclass
class Incident:
    id: str
    blurb: str


@dataclass
class Binding:
    concept: str
    subsystem: str
    incident: Optional[str] = None  # incident id, or None


@dataclass
class Narrative:
    version: int
    seed: int
    mode: str
    theme: str
    domain: str
    subsystems: List[str]
    vocab: List[str]
    incidents: List[Incident]
    lore: List[str]
    glossary: Dict[str, Binding] = field(default_factory=dict)

    # -- binding (the consistency root) -----------------------------------

    def bind(self, entity_key: str) -> Binding:
        """Return the stable fake identity for ``entity_key``.

        Deterministic in ``(seed, entity_key)`` and memoized, so the same entity
        always maps to the same concept/subsystem/incident across every file and
        every surface. This is what makes the lie self-consistent.
        """
        cached = self.glossary.get(entity_key)
        if cached is not None:
            return cached
        concept = self.vocab[_h(self.seed, "concept", entity_key) % len(self.vocab)]
        subsystem = self.subsystems[
            _h(self.seed, "subsystem", entity_key) % len(self.subsystems)
        ]
        incident = None
        if self.incidents and _h(self.seed, "hasinc", entity_key) % 100 < 55:
            incident = self.incidents[
                _h(self.seed, "inc", entity_key) % len(self.incidents)
            ].id
        binding = Binding(concept=concept, subsystem=subsystem, incident=incident)
        self.glossary[entity_key] = binding
        return binding

    def incident_by_id(self, incident_id: Optional[str]) -> Optional[Incident]:
        if not incident_id:
            return None
        return next((i for i in self.incidents if i.id == incident_id), None)

    # -- (de)serialization -------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "seed": self.seed,
            "mode": self.mode,
            "theme": self.theme,
            "domain": self.domain,
            "subsystems": list(self.subsystems),
            "vocab": list(self.vocab),
            "incidents": [{"id": i.id, "blurb": i.blurb} for i in self.incidents],
            "lore": list(self.lore),
            "glossary": {
                k: {"concept": b.concept, "subsystem": b.subsystem, "incident": b.incident}
                for k, b in self.glossary.items()
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Narrative":
        return cls(
            version=d["version"],
            seed=d["seed"],
            mode=d["mode"],
            theme=d["theme"],
            domain=d["domain"],
            subsystems=list(d["subsystems"]),
            vocab=list(d["vocab"]),
            incidents=[Incident(**i) for i in d["incidents"]],
            lore=list(d["lore"]),
            glossary={
                k: Binding(**v) for k, v in d.get("glossary", {}).items()
            },
        )


# --------------------------------------------------------------------------- #
# Build / persist
# --------------------------------------------------------------------------- #

def narrative_path(root) -> Path:
    return Path(root) / JUNKMAP_DIR / NARRATIVE_NAME


def save_narrative(narrative: Narrative, root) -> None:
    """Persist the artifact under ``.junkmap/`` (secret; git-ignored)."""
    path = narrative_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(narrative.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _build_template(seed: int, theme_name: Optional[str] = None) -> Narrative:
    rng = random.Random(seed)
    if theme_name and theme_name in THEMES:
        theme = THEMES[theme_name]
    else:
        names = sorted(THEMES)
        theme = THEMES[names[_h(seed, "theme") % len(names)]]

    blurbs = list(theme.incident_blurbs)
    rng.shuffle(blurbs)
    incidents: List[Incident] = []
    used: set = set()
    for blurb in blurbs[: min(3, len(blurbs))]:
        year = 2017 + (_h(seed, "year", blurb) % 5)
        num = _h(seed, "num", blurb) % 9000 + 1000
        incident_id = f"INC-{year}-{num:04d}"
        if incident_id in used:
            continue
        used.add(incident_id)
        incidents.append(Incident(id=incident_id, blurb=blurb))

    return Narrative(
        version=SCHEMA_VERSION,
        seed=seed,
        mode="template",
        theme=theme.name,
        domain=theme.domain,
        subsystems=list(theme.subsystems),
        vocab=list(theme.vocab),
        incidents=incidents,
        lore=list(theme.lore),
        glossary={},
    )


def build_narrative(
    files: Sequence,
    seed: int,
    mode: str = "template",
    root=None,
    *,
    theme: Optional[str] = None,
    refresh: bool = False,
) -> Narrative:
    """Build (or reuse) the run's narrative artifact.

    Idempotent: a cached ``narrative.json`` matching ``(seed, mode)`` is reused
    unless ``refresh`` is set. ``files`` is accepted for signature stability and
    used by the (future) LLM mode to read structure; template mode ignores it.
    """
    root = Path(root or Path.cwd()).resolve()
    path = narrative_path(root)
    if not refresh and path.exists():
        try:
            existing = Narrative.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if existing.seed == seed and existing.mode == mode:
                return existing
        except Exception:  # noqa: BLE001 - a corrupt cache just gets rebuilt
            pass

    if mode == "template":
        narrative = _build_template(seed, theme)
    elif mode == "llm":
        raise NotImplementedError("llm narrative mode is not implemented yet")
    else:
        raise ValueError(f"unknown narrative mode: {mode!r}")

    save_narrative(narrative, root)
    return narrative


# --------------------------------------------------------------------------- #
# Renderers — every surface draws its text from here
# --------------------------------------------------------------------------- #

def render_module_docstring(narrative: Narrative, base_key: str, rng: random.Random) -> str:
    binding = narrative.bind(f"{base_key}::<module>")
    options = [
        f"{narrative.domain} — {binding.subsystem} module.",
        f"Part of the {narrative.domain}. Implements the {binding.subsystem}.",
        f"{binding.subsystem.capitalize()} for the {narrative.domain}.",
    ]
    text = rng.choice(options)
    if binding.incident and rng.random() < 0.5:
        text += f" Hardened after {binding.incident}."
    return text


def render_docstring(narrative: Narrative, binding: Binding, rng: random.Random) -> str:
    pieces = [f"Drives {binding.concept} within the {binding.subsystem}."]
    options = [
        f"Invariant: {rng.choice(narrative.lore)}." if narrative.lore else "",
        f"Part of the {binding.subsystem}; do not reorder relative to the "
        f"{narrative.subsystems[0]}.",
        "Thread-safe only while the registry lock is held.",
    ]
    options = [o for o in options if o]
    if options:
        pieces.append(rng.choice(options))
    incident = narrative.incident_by_id(binding.incident)
    if incident:
        pieces.append(f"See {incident.id} ({incident.blurb}).")
    return " ".join(pieces)


def render_comment(narrative: Narrative, binding: Binding, rng: random.Random) -> str:
    options = [
        f"{binding.concept}: guarded by the {binding.subsystem} barrier",
        f"routed through the {binding.subsystem}; ordering matters",
    ]
    if narrative.lore:
        options.append(f"NOTE: {rng.choice(narrative.lore)}")
    if binding.incident:
        options.append(f"workaround for {binding.incident} - do not touch")
    return rng.choice(options)


def decoy_name(narrative: Narrative, entity_key: str) -> str:
    """A deterministic, story-aligned identifier for injected dead code."""
    binding = narrative.bind(entity_key)
    if binding.incident:
        digits = "".join(ch for ch in binding.incident if ch.isdigit())[-4:]
        return f"_{binding.concept}_{digits}_workaround"
    return f"_{binding.concept}_shim"


def render_test_name(binding: Binding, original: str) -> str:
    """Rename a ``test_*`` function, keeping the ``test_`` prefix for discovery."""
    if original.startswith("test_"):
        tail = original[len("test_"):]
        return f"test_{binding.concept}_{tail}" if tail else f"test_{binding.concept}"
    return f"test_{binding.concept}"


def render_architecture_doc(narrative: Narrative) -> str:
    """Render a decoy architecture doc from the (post-run) populated narrative."""
    lines: List[str] = [
        f"# Architecture — {narrative.domain}",
        "",
        f"> Internal engineering notes for the {narrative.domain}.",
        "",
        "## Subsystems",
        "",
    ]
    lines += [f"- **{s}**" for s in narrative.subsystems]
    lines += ["", "## Invariants", ""]
    lines += [f"- {item}" for item in narrative.lore]
    if narrative.incidents:
        lines += ["", "## Incident history", ""]
        lines += [f"- `{i.id}` - {i.blurb}" for i in narrative.incidents]
    if narrative.glossary:
        lines += ["", "## Module map", "", "| entity | subsystem | concept |", "|---|---|---|"]
        for key, binding in sorted(narrative.glossary.items()):
            lines.append(f"| `{key}` | {binding.subsystem} | {binding.concept} |")
    return "\n".join(lines) + "\n"
