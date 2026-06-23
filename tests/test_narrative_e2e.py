"""End-to-end: narrative (template) mode through the obfuscate/restore path."""

import re

from junk import core

ALPHA = "def add(a, b):\n    total = a + b\n    return total\n"
BETA = "from pkg.alpha import add\n\n\ndef combine(a, b):\n    return add(a, b)\n"
TEST = "from pkg.alpha import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def _project(root):
    (root / "pkg").mkdir()
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "alpha.py").write_text(ALPHA, encoding="utf-8")
    (root / "pkg" / "beta.py").write_text(BETA, encoding="utf-8")
    (root / "tests" / "test_pkg.py").write_text(TEST, encoding="utf-8")


def test_narrative_end_to_end(tmp_path):
    _project(tmp_path)
    originals = {
        p: (tmp_path / p).read_bytes()
        for p in ("pkg/alpha.py", "pkg/beta.py", "tests/test_pkg.py")
    }

    res = core.obfuscate(
        ["pkg", "tests"], aggressive=True, tests=None, seed=42,
        root=tmp_path, narrative_mode="template", rename_tests=True,
    )
    assert res.ok and not res.rolled_back, res.reason

    arch = tmp_path / "ARCHITECTURE.md"
    assert arch.exists()
    assert (tmp_path / ".junkmap" / "narrative.json").exists()

    # behaviour preserved: the obfuscated module still computes the same thing
    alpha = (tmp_path / "pkg" / "alpha.py").read_text(encoding="utf-8")
    ns: dict = {}
    exec(compile(alpha, "alpha", "exec"), ns)  # noqa: S102 - exercising our own output
    assert ns["add"](2, 3) == 5

    # cross-surface agreement: some incident id appears in BOTH a .py file and the doc
    archt = arch.read_text(encoding="utf-8")
    ids = set(re.findall(r"INC-\d{4}-\d{4}", alpha + archt))
    assert any(i in alpha and i in archt for i in ids)

    # tests renamed to narrative vocabulary but still pytest-discoverable
    test_after = (tmp_path / "tests" / "test_pkg.py").read_text(encoding="utf-8")
    assert "def test_add(" not in test_after
    assert re.search(r"def test_\w+\(", test_after)

    # restore: byte-exact originals + decoy doc removed
    core.restore([], root=tmp_path)
    for p, original in originals.items():
        assert (tmp_path / p).read_bytes() == original
    assert not arch.exists()


def test_narrative_off_is_inert(tmp_path):
    """Default (off) must not build a narrative or emit decoy docs."""
    _project(tmp_path)
    res = core.obfuscate(["pkg"], aggressive=True, tests=None, seed=1, root=tmp_path)
    assert res.ok
    assert not (tmp_path / "ARCHITECTURE.md").exists()
    assert not (tmp_path / ".junkmap" / "narrative.json").exists()
