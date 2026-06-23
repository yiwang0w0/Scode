"""Tests for the offline template-mode narrative core."""

import random

from junk import narrative as nar


def test_build_is_deterministic_and_cached(tmp_path):
    a = nar.build_narrative([], seed=7, mode="template", root=tmp_path)
    # second call hits the cache (same seed+mode) and returns identical content
    b = nar.build_narrative([], seed=7, mode="template", root=tmp_path)
    assert a.to_dict() == b.to_dict()
    assert nar.narrative_path(tmp_path).exists()


def test_different_seeds_differ(tmp_path):
    a = nar.build_narrative([], seed=1, mode="template", root=tmp_path / "a")
    b = nar.build_narrative([], seed=2, mode="template", root=tmp_path / "b")
    # incident ids are minted from the seed, so distinct seeds diverge
    assert a.to_dict() != b.to_dict()


def test_binding_is_stable_across_rebuilds():
    """Same entity_key -> same concept, regardless of run — the consistency root."""
    n1 = nar._build_template(seed=5)
    n2 = nar._build_template(seed=5)
    key = "junk/core.py::obfuscate"
    assert n1.bind(key) == n2.bind(key)
    # memoized: asking twice returns the identical binding
    assert n1.bind(key) is n1.bind(key)
    # a different entity generally gets a different concept
    other = n1.bind("junk/snapshot.py::SnapshotStore")
    assert isinstance(other.concept, str)


def _incident_key(narrative) -> str:
    for i in range(200):
        key = f"junk/mod.py::entity_{i}"
        if narrative.bind(key).incident:
            return key
    raise AssertionError("no entity bound to an incident (binding probability bug?)")


def test_incident_is_self_consistent():
    """An incident cited in rendered prose must exist in the narrative registry."""
    narrative = nar._build_template(seed=11)
    key = _incident_key(narrative)
    binding = narrative.bind(key)

    rng = random.Random(0)
    doc = nar.render_docstring(narrative, binding, rng)
    assert binding.incident in doc  # the id is rendered verbatim
    # and that id is a real registered incident — cross-surface agreement
    assert narrative.incident_by_id(binding.incident) is not None
    assert binding.incident in {inc.id for inc in narrative.incidents}


def test_decoy_name_and_test_name_shapes():
    narrative = nar._build_template(seed=3)
    binding = narrative.bind("junk/core.py::obfuscate")
    decoy = nar.decoy_name(narrative, "junk/core.py::obfuscate")
    assert decoy.startswith("_") and binding.concept in decoy

    renamed = nar.render_test_name(binding, "test_roundtrip_byte_identical")
    assert renamed.startswith("test_")
    assert binding.concept in renamed


def test_architecture_doc_reflects_the_story():
    narrative = nar._build_template(seed=9)
    # populate the glossary the way a real run would
    narrative.bind("junk/core.py::obfuscate")
    narrative.bind("junk/gates.py::run_gates")
    doc = nar.render_architecture_doc(narrative)
    assert narrative.domain in doc
    assert "## Incident history" in doc
    assert narrative.incidents[0].id in doc
    assert "junk/core.py::obfuscate" in doc  # the module map cross-references entities
