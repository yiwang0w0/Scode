"""Agent-cost harness: the honest fitness function for "Agent maze" mode.

``redteam`` asks one model how confident it *feels*. This harness instead lets a
tool-using agent actually navigate the obfuscated tree and measures what the maze
costs it — turns, tool calls, tokens — and, using the clean source as ground
truth, whether it ends up **confidently wrong** (adopts the fabricated cover
story). That last signal is the real objective: a snooper who walks away with a
confident-but-false understanding is the best outcome for the defender.

The offline-testable pieces (the :class:`Sandbox` the agent navigates, the
narrative-adoption detector, the clean-corpus reconstruction) have no API
dependency. The agent loop and the correctness judge need the ``anthropic``
package and ``ANTHROPIC_API_KEY`` (optional, like ``redteam``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from junk.snapshot import JUNKMAP_DIR, SnapshotStore
from junk.narrative import NARRATIVE_NAME, Narrative

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_TASK = (
    "Determine the REAL purpose of this codebase and what its main module does. "
    "Navigate with the tools, then call final_answer."
)


# --------------------------------------------------------------------------- #
# Sandbox the agent navigates (offline, no API)
# --------------------------------------------------------------------------- #

class Sandbox:
    """Read-only view of a tree, excluding ``.junkmap/`` (which holds the answer)."""

    def __init__(self, root, exts=(".py", ".md")):
        self.root = Path(root).resolve()
        self.exts = exts

    def _resolve(self, rel: str) -> Path:
        target = (self.root / rel).resolve()
        relative = target.relative_to(self.root)  # raises ValueError if escaping
        if JUNKMAP_DIR in relative.parts:
            raise ValueError("path is out of bounds")
        return target

    def list_files(self) -> List[str]:
        out: List[str] = []
        for path in sorted(self.root.rglob("*")):
            relative = path.relative_to(self.root)
            if JUNKMAP_DIR in relative.parts:
                continue
            if path.is_file() and path.suffix in self.exts:
                out.append(relative.as_posix())
        return out

    def read_file(self, rel: str) -> str:
        try:
            path = self._resolve(rel)
        except ValueError:
            return f"error: out-of-bounds path: {rel}"
        if not path.is_file():
            return f"error: no such file: {rel}"
        return path.read_text(encoding="utf-8", errors="replace")

    def grep(self, pattern: str, max_hits: int = 80) -> str:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return f"error: bad regex: {exc}"
        hits: List[str] = []
        for rel in self.list_files():
            for i, line in enumerate(self.read_file(rel).splitlines(), start=1):
                if rx.search(line):
                    hits.append(f"{rel}:{i}:{line.strip()}")
                    if len(hits) >= max_hits:
                        return "\n".join(hits)
        return "\n".join(hits) if hits else "(no matches)"


# --------------------------------------------------------------------------- #
# Ground truth + adoption detection (offline, no API)
# --------------------------------------------------------------------------- #

def load_narrative(root) -> Optional[Narrative]:
    path = Path(root) / JUNKMAP_DIR / NARRATIVE_NAME
    if not path.exists():
        return None
    try:
        return Narrative.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return None


def detect_narrative_adoption(answer: str, narrative: Narrative) -> List[str]:
    """Return the fabricated terms the answer parroted back (>=2 == adoption)."""
    text = answer.lower()
    terms = {narrative.domain.lower()}
    terms.update(s.lower() for s in narrative.subsystems)
    for v in narrative.vocab:
        terms.add(v.lower())
        terms.add(v.replace("_", " ").lower())
    terms.update(i.id.lower() for i in narrative.incidents)
    return sorted(t for t in terms if t and t in text)


def clean_corpus(store: SnapshotStore, limit: int = 16000) -> str:
    """Reconstruct the clean source from snapshots, as ground truth for grading."""
    parts: List[str] = []
    for key, entry in sorted(store.entries().items()):
        blob_id = entry.get("blob")
        if not blob_id:
            continue
        blob = store.blobs / blob_id
        if not blob.exists():
            continue
        parts.append(f"# === {key} ===\n" + blob.read_bytes().decode("utf-8", "replace"))
    return "\n\n".join(parts)[:limit]


# --------------------------------------------------------------------------- #
# Agent run result
# --------------------------------------------------------------------------- #

@dataclass
class AgentRun:
    answer: str = ""
    confidence: Optional[int] = None
    turns: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    terminated: bool = False  # did it call final_answer (vs run out of turns)?
    tool_log: List[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


_TOOLS = [
    {
        "name": "list_files",
        "description": "List every source file in the project.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_file",
        "description": "Read one file's full contents.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "grep",
        "description": "Search all files for a regex; returns path:line:text hits.",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
    },
    {
        "name": "final_answer",
        "description": "Report the code's real purpose and your confidence (0-100).",
        "input_schema": {
            "type": "object",
            "properties": {
                "purpose": {"type": "string"},
                "confidence": {"type": "integer"},
            },
            "required": ["purpose", "confidence"],
        },
    },
]


def _dispatch(sandbox: Sandbox, name: str, args: dict) -> str:
    if name == "list_files":
        return "\n".join(sandbox.list_files()) or "(empty)"
    if name == "read_file":
        return sandbox.read_file(args.get("path", ""))
    if name == "grep":
        return sandbox.grep(args.get("pattern", ""))
    return f"error: unknown tool {name}"


def run_agent(client, model: str, sandbox: Sandbox, task: str, max_turns: int = 12) -> AgentRun:
    """Drive a tool-using agent over ``sandbox`` and tally what it cost."""
    run = AgentRun()
    messages = [{
        "role": "user",
        "content": (
            "You are reverse-engineering an unfamiliar Python codebase to find its "
            "REAL purpose. Use the tools to navigate; do not trust comments or names "
            "blindly. When confident, call final_answer.\n\nTask: " + task
        ),
    }]

    for _ in range(max_turns):
        resp = client.messages.create(
            model=model, max_tokens=1024, tools=_TOOLS, messages=messages,
        )
        run.turns += 1
        usage = getattr(resp, "usage", None)
        if usage:
            run.input_tokens += getattr(usage, "input_tokens", 0) or 0
            run.output_tokens += getattr(usage, "output_tokens", 0) or 0

        messages.append({"role": "assistant", "content": resp.content})
        tool_uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        if not tool_uses:
            # plain text without a final_answer call — take it as the answer
            run.answer = "".join(
                getattr(b, "text", "") for b in resp.content
                if getattr(b, "type", "") == "text"
            ).strip()
            break

        results = []
        finished = False
        for tu in tool_uses:
            run.tool_calls += 1
            if tu.name == "final_answer":
                run.answer = str(tu.input.get("purpose", "")).strip()
                run.confidence = tu.input.get("confidence")
                run.terminated = True
                finished = True
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "recorded"})
                continue
            output = _dispatch(sandbox, tu.name, dict(tu.input or {}))
            run.tool_log.append(f"{tu.name}({dict(tu.input or {})})")
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": output})
        messages.append({"role": "user", "content": results})
        if finished:
            break

    return run


def judge_correctness(client, model: str, answer: str, truth: str) -> int:
    """0-100: how accurately ``answer`` describes what ``truth`` really does."""
    prompt = (
        "Below is the TRUE source of a small program, then a stranger's guess at "
        "its purpose. Score 0-100 how accurately the guess matches what the code "
        "really does (0 = wrong/misled, 100 = spot on). Reply with ONLY the integer.\n\n"
        f"=== TRUE SOURCE ===\n{truth}\n\n=== GUESS ===\n{answer}\n"
    )
    try:
        resp = client.messages.create(
            model=model, max_tokens=8,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        )
        match = re.search(r"\d+", text)
        return max(0, min(100, int(match.group()))) if match else 0
    except Exception as exc:  # noqa: BLE001
        print(f"  (judge error: {exc})")
        return -1


def _report(label: str, run: AgentRun, adoption: List[str], correctness: Optional[int]) -> None:
    print(f"\n[{label}]")
    print(f"  terminated      : {run.terminated} (turns={run.turns}, tool_calls={run.tool_calls})")
    print(f"  tokens          : {run.total_tokens} (in={run.input_tokens}, out={run.output_tokens})")
    print(f"  self-confidence : {run.confidence}")
    if correctness is not None and correctness >= 0:
        print(f"  correctness     : {correctness}/100 (judged vs clean source)")
    if adoption:
        print(f"  NARRATIVE ADOPTED: {', '.join(adoption)}")
    if run.confidence is not None and correctness not in (None, -1):
        wrong = run.confidence >= 60 and correctness < 40
        print(f"  confidently wrong: {wrong}  <-- the maze's win condition")
    print(f"  answer          : {run.answer[:300]}")


def maze_eval(
    paths,
    task: str = DEFAULT_TASK,
    model: str = DEFAULT_MODEL,
    max_turns: int = 12,
    baseline: bool = False,
    root: Optional[Path] = None,
) -> int:
    """Run the agent over the (obfuscated) tree and report cost + adoption."""
    try:
        import anthropic
    except ImportError:
        print("maze-eval requires the 'anthropic' package: pip install 'junk[redteam]'")
        return 1
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("maze-eval requires the ANTHROPIC_API_KEY environment variable.")
        return 1

    root = Path(root or Path.cwd()).resolve()
    client = anthropic.Anthropic()
    store = SnapshotStore(root)
    narrative = load_narrative(root)
    truth = clean_corpus(store)

    obf_run = run_agent(client, model, Sandbox(root), task, max_turns)
    adoption = detect_narrative_adoption(obf_run.answer, narrative) if narrative else []
    correctness = judge_correctness(client, model, obf_run.answer, truth) if truth else None
    _report("obfuscated", obf_run, adoption, correctness)

    if baseline and truth:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            for key, entry in store.entries().items():
                blob_id = entry.get("blob")
                if not blob_id:
                    continue
                blob = store.blobs / blob_id
                if not blob.exists():
                    continue
                dest = tmp_root / key
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(blob.read_bytes())
            base_run = run_agent(client, model, Sandbox(tmp_root), task, max_turns)
            base_correct = judge_correctness(client, model, base_run.answer, truth)
            _report("clean baseline", base_run, [], base_correct)
            print(
                f"\nDELTA (maze cost): +{obf_run.total_tokens - base_run.total_tokens} tokens, "
                f"+{obf_run.tool_calls - base_run.tool_calls} tool calls"
            )

    return 0
