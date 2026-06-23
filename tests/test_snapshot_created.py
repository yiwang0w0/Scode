"""Tests for the 'created' snapshot entry (decoy files deleted on restore)."""

from junk.snapshot import SnapshotStore


def test_created_entry_is_deleted_on_restore(tmp_path):
    store = SnapshotStore(tmp_path)
    decoy = tmp_path / "ARCHITECTURE.md"
    decoy.write_text("# fake architecture\n", encoding="utf-8")
    store.mark_created(decoy)

    assert store.is_obfuscated(decoy)
    assert store.restore_key(store.key_for(decoy)) is True
    assert not decoy.exists()              # restore deletes, not writes-back
    assert not store.is_obfuscated(decoy)  # entry dropped


def test_normal_entry_still_byte_restores(tmp_path):
    store = SnapshotStore(tmp_path)
    f = tmp_path / "mod.py"
    original = b"x = 1\n"
    f.write_bytes(original)

    store.snapshot(f)
    f.write_bytes(b"# obfuscated garbage\n")
    assert store.restore(f) is True
    assert f.read_bytes() == original
