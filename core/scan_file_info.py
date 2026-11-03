"""Format version and software information stamped into scan JSON files.

Every scan JSON that ZMeter writes (scan output, recovery and backup copies,
manual save, autosave, scan setting files and the scan files of a saved queue)
carries two top-level fields:

``format_version``
    Integer version of the scan JSON layout, ``SCAN_FORMAT_VERSION``. A file
    without it was written before this field existed and is read as version 1.
``software``
    Which ZMeter code wrote the file, from ``software_info()``.

This module is Qt-free and never runs ``git``: the version comes from files
that are already on disk, and any read error falls back to
``{"source": "unknown"}`` so saving is never blocked.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

SCAN_FORMAT_VERSION = 1

MANIFEST_NAME = "deployment-manifest.json"
REPO_ROOT = Path(__file__).resolve().parents[1]

_MANIFEST_FIELDS = ("version", "tag", "channel", "commit")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_cached_software_info = None


def _from_manifest(root: Path):
    path = root / MANIFEST_NAME
    if not path.is_file():
        return None
    # The release workflow writes the manifest with PowerShell; accept a BOM.
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError(f"{MANIFEST_NAME} is not a JSON object")
    info = {"source": "release"}
    for field in _MANIFEST_FIELDS:
        value = manifest.get(field)
        info[field] = None if value is None else str(value)
    return info


def _git_dir(root: Path):
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        # Worktrees and submodules: ".git" is a file "gitdir: <path>".
        text = dot_git.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            target = Path(text[len("gitdir:"):].strip())
            if not target.is_absolute():
                target = (root / target).resolve()
            if target.is_dir():
                return target
    return None


def _common_dir(git_dir: Path) -> Path:
    commondir = git_dir / "commondir"
    if commondir.is_file():
        target = Path(commondir.read_text(encoding="utf-8").strip())
        if not target.is_absolute():
            target = (git_dir / target).resolve()
        return target
    return git_dir


def _resolve_ref(git_dir: Path, ref: str):
    for base in dict.fromkeys((git_dir, _common_dir(git_dir))):
        loose = base / ref
        if loose.is_file():
            value = loose.read_text(encoding="utf-8").strip()
            if _SHA_PATTERN.match(value):
                return value
        packed = base / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if not line or line[0] in "#^":
                    continue
                sha, _, name = line.partition(" ")
                if name.strip() == ref and _SHA_PATTERN.match(sha):
                    return sha
    return None


def _from_git(root: Path):
    git_dir = _git_dir(root)
    if git_dir is None:
        return None
    head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    if head.startswith("ref:"):
        ref = head[len("ref:"):].strip()
        branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
        return {"source": "git", "branch": branch, "commit": _resolve_ref(git_dir, ref)}
    if _SHA_PATTERN.match(head):
        return {"source": "git", "branch": None, "commit": head}
    raise ValueError("unrecognized .git/HEAD content")


def read_software_info(root=REPO_ROOT) -> dict:
    """Describe the code at ``root``: a release install, a git clone, or unknown.

    A release install has ``deployment-manifest.json`` at its root (written by
    the release workflow) and no ``.git``. A developer clone has ``.git`` and
    no manifest. If both are present the manifest wins.
    """
    root = Path(root)
    for reader in (_from_manifest, _from_git):
        try:
            info = reader(root)
        except (OSError, UnicodeError, ValueError):
            return {"source": "unknown"}
        if info is not None:
            return info
    return {"source": "unknown"}


def software_info() -> dict:
    """``read_software_info()`` for this checkout, computed once per process."""
    global _cached_software_info
    if _cached_software_info is None:
        _cached_software_info = read_software_info()
    return copy.deepcopy(_cached_software_info)


def stamp_scan_payload(payload: dict) -> dict:
    """Return a shallow copy of ``payload`` with the current format and software.

    The two fields come first in the written file. Values already in
    ``payload`` (for example from a loaded file) are replaced: the new file
    describes the code that writes it. ``payload`` itself is not changed.
    """
    stamped = {
        "format_version": SCAN_FORMAT_VERSION,
        "software": software_info(),
    }
    for key, value in payload.items():
        if key not in stamped:
            stamped[key] = value
    return stamped


def scan_format_version(info: dict) -> int:
    """Format version of a loaded scan dictionary; files without one are 1.

    Raises ``ValueError`` for a version this ZMeter cannot read: not a
    positive integer, or newer than ``SCAN_FORMAT_VERSION``.
    """
    version = info.get("format_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError(f"Invalid scan format_version: {version!r}")
    if version > SCAN_FORMAT_VERSION:
        raise ValueError(
            f"This file uses scan format_version {version}, written by a newer "
            f"ZMeter; this version reads up to format_version "
            f"{SCAN_FORMAT_VERSION}. Update ZMeter to open it."
        )
    return version


__all__ = [
    "MANIFEST_NAME",
    "SCAN_FORMAT_VERSION",
    "read_software_info",
    "scan_format_version",
    "software_info",
    "stamp_scan_payload",
]
