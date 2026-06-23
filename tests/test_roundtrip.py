"""End-to-end tests for junk's core guarantees."""

from junk import core

SAMPLE = '''\
"""Original module docstring."""

GREETING = "hi"


def add(a, b):
    result = a + b
    return result


def scale(values, factor):
    out = []
    for v in values:
        out.append(v * factor)
    return out


class Counter:
    """A counter."""

    def __init__(self):
        self.n = 0

    def bump(self, by=1):
        step = by
        self.n = self.n + step
        return self.n
'''


def _write(tmp_path, text=SAMPLE):
    f = tmp_path / "mod.py"
    f.write_text(text, encoding="utf-8")
    return f


def test_roundtrip_byte_identical(tmp_path):
    """obfuscate -> gate -> restore reproduces the original byte-for-byte."""
    f = _write(tmp_path)

    result = core.obfuscate(
        [f], aggressive=True, tests=None, bench=None, seed=1, root=tmp_path
    )
    assert result.ok and not result.blocked and not result.rolled_back

    obfuscated = f.read_text(encoding="utf-8")
    assert obfuscated != SAMPLE  # it actually changed
    compile(obfuscated, str(f), "exec")  # still valid Python
    assert core.is_obfuscated(f, root=tmp_path)

    restored = core.restore([f], root=tmp_path)
    assert len(restored) == 1
    assert f.read_text(encoding="utf-8") == SAMPLE
    assert not core.is_obfuscated(f, root=tmp_path)


def test_gate_failure_rolls_back(tmp_path):
    """A failing test gate must restore the file untouched."""
    f = _write(tmp_path)
    failing = 'python -c "import sys; sys.exit(1)"'

    result = core.obfuscate(
        [f], aggressive=True, tests=failing, bench=None, seed=2, root=tmp_path
    )
    assert not result.ok
    assert result.rolled_back
    assert f.read_text(encoding="utf-8") == SAMPLE
    assert not core.is_obfuscated(f, root=tmp_path)


def test_double_obfuscation_blocked(tmp_path):
    """Obfuscating an already-obfuscated file is refused (protects reversibility)."""
    f = _write(tmp_path)

    first = core.obfuscate(
        [f], aggressive=False, tests=None, bench=None, seed=3, root=tmp_path
    )
    assert first.ok

    second = core.obfuscate(
        [f], aggressive=False, tests=None, bench=None, seed=3, root=tmp_path
    )
    assert not second.ok
    assert second.blocked
    # the file is still the (first) obfuscated version, snapshot intact
    assert core.is_obfuscated(f, root=tmp_path)
    assert core.restore([f], root=tmp_path) == ["mod.py"]
    assert f.read_text(encoding="utf-8") == SAMPLE
