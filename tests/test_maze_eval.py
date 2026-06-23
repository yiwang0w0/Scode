"""Offline tests for the maze-eval harness (no API needed)."""

from junk import maze_eval as me
from junk import narrative as nar
from junk.snapshot import SnapshotStore


def _tree(root):
    (root / "pkg").mkdir()
    (root / "pkg" / "a.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "ARCHITECTURE.md").write_text("# fake\n", encoding="utf-8")
    junkmap = root / ".junkmap"
    junkmap.mkdir()
    (junkmap / "manifest.json").write_text("{\"secret\": true}", encoding="utf-8")


def test_sandbox_lists_sources_but_hides_junkmap(tmp_path):
    _tree(tmp_path)
    box = me.Sandbox(tmp_path)
    files = box.list_files()
    assert "pkg/a.py" in files
    assert "ARCHITECTURE.md" in files
    assert all(".junkmap" not in f for f in files)


def test_sandbox_refuses_junkmap_and_escapes(tmp_path):
    _tree(tmp_path)
    box = me.Sandbox(tmp_path)
    assert "out-of-bounds" in box.read_file(".junkmap/manifest.json")
    assert "out-of-bounds" in box.read_file("../outside.py")
    assert "no such file" in box.read_file("pkg/missing.py")
    assert "return a + b" in box.read_file("pkg/a.py")


def test_sandbox_grep(tmp_path):
    _tree(tmp_path)
    box = me.Sandbox(tmp_path)
    hits = box.grep(r"def add")
    assert "pkg/a.py:1:" in hits
    assert box.grep(r"nonexistent_zzz") == "(no matches)"


def test_detect_narrative_adoption():
    narrative = nar._build_template(seed=5)
    fooled = f"This is a {narrative.domain} built around a {narrative.subsystems[0]}."
    assert len(me.detect_narrative_adoption(fooled, narrative)) >= 2
    clean = "This is a tiny library that adds two integers together."
    assert me.detect_narrative_adoption(clean, narrative) == []


def test_clean_corpus_reconstructs_from_snapshots(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def real():\n    return 42\n", encoding="utf-8")
    store = SnapshotStore(tmp_path)
    store.snapshot(f)
    f.write_text("# obfuscated\n", encoding="utf-8")  # corrupt the live file

    corpus = me.clean_corpus(store)
    assert "def real()" in corpus      # ground truth comes from the snapshot blob
    assert "=== mod.py ===" in corpus
