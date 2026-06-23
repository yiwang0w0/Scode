"""Byte-exact snapshot store backing junk's reversibility.

The store lives in ``<root>/.junkmap/`` and is the single source of truth for
restoration. Restore never parses the obfuscated source — it writes the original
bytes straight back from a content-addressed blob — so transforms may be as
aggressive as they like with zero risk of information loss.

Layout::

    .junkmap/
        manifest.json        # path -> {original_sha256, blob, obfuscated_sha256, ...}
        blobs/<sha256>        # verbatim original file bytes, deduplicated by hash
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

JUNKMAP_DIR = ".junkmap"
MANIFEST_NAME = "manifest.json"
BLOBS_DIRNAME = "blobs"


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


class SnapshotStore:
    """A content-addressed store of original file bytes, keyed by relative path."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.dir = self.root / JUNKMAP_DIR
        self.blobs = self.dir / BLOBS_DIRNAME
        self.manifest_path = self.dir / MANIFEST_NAME
        self._manifest: Optional[dict] = None

    # -- manifest plumbing -------------------------------------------------

    def _load(self) -> dict:
        if self._manifest is None:
            if self.manifest_path.exists():
                self._manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            else:
                self._manifest = {"version": 1, "entries": {}}
        return self._manifest

    def _save(self) -> None:
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(self._load(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def key_for(self, path) -> str:
        """Return the manifest key (posix relative path) for ``path``."""
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        return p.resolve().relative_to(self.root).as_posix()

    # -- public API --------------------------------------------------------

    def entries(self) -> dict:
        return dict(self._load()["entries"])

    def is_obfuscated(self, path) -> bool:
        """True if the file is currently under junk's management (snapshotted)."""
        return self.key_for(path) in self._load()["entries"]

    def snapshot(self, path) -> str:
        """Store the original bytes of ``path`` and register a manifest entry.

        Returns the original SHA-256. Idempotent on the blob (deduplicated).
        """
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        data = p.read_bytes()
        sha = sha256_bytes(data)
        self.blobs.mkdir(parents=True, exist_ok=True)
        blob = self.blobs / sha
        if not blob.exists():
            blob.write_bytes(data)
        entries = self._load()["entries"]
        entries[self.key_for(path)] = {
            "original_sha256": sha,
            "blob": sha,
            "obfuscated_sha256": None,
            "snapshot_at": time.time(),
        }
        self._save()
        return sha

    def mark_obfuscated(self, path, obfuscated_sha: str) -> None:
        """Record the post-obfuscation hash for a snapshotted file."""
        entries = self._load()["entries"]
        key = self.key_for(path)
        if key in entries:
            entries[key]["obfuscated_sha256"] = obfuscated_sha
            self._save()

    def restore_key(self, key: str) -> bool:
        """Restore one file by manifest key. Returns True if restored."""
        entries = self._load()["entries"]
        entry = entries.get(key)
        if entry is None:
            return False
        blob = self.blobs / entry["blob"]
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob.read_bytes())
        del entries[key]
        self._save()
        return True

    def restore(self, path) -> bool:
        """Restore one file by path. Returns True if restored."""
        return self.restore_key(self.key_for(path))


def ensure_gitignore(root: Path) -> None:
    """Make sure ``.junkmap/`` is git-ignored at ``root``.

    The snapshot store is the master key to your original source — it must never
    leave the machine.
    """
    gi = Path(root) / ".gitignore"
    needle = f"{JUNKMAP_DIR}/"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    lines = {ln.strip() for ln in existing.splitlines()}
    if needle in lines or JUNKMAP_DIR in lines:
        return
    prefix = "" if existing.endswith("\n") or existing == "" else "\n"
    with gi.open("a", encoding="utf-8") as fh:
        fh.write(f"{prefix}{needle}\n")
