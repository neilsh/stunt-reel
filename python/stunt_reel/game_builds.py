"""Build the unpatched and the Patch #3 game trees beside the read-only corpus.

``corpus/stuntisl`` ships the original 1992 executables. Disney's Patch #3 (``corpus/patches``)
replaces them: ``PATSI.BAT`` deletes eleven files, then runs ``P3-SI1`` to ``P3-SI5 -d``,
PKLITE self-extracting zips that Python's :mod:`zipfile` opens. Nothing may write the corpus
(ADR 0022), so both trees are copies under the data root's ``builds/`` directory, each built
whole in a temporary directory and only then moved into place, with a manifest of every file
the patch added, replaced or deleted.

``PATSI.BAT`` deletes ``GAME.CFG`` and then runs ``SETUP`` (``install -s``) to write a new
one; the patched ``INSTALL.EXE`` writes the same seven-byte layout as the original
(``research/playone-exe/patch3.md``), so the patched tree keeps the shipped ``GAME.CFG``
instead of running the installer, and the manifest says so.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

__all__ = [
    "BUILDS_DIR",
    "BUILD_NAMES",
    "MANIFEST_NAME",
    "PATCH3_ARCHIVES",
    "PATCH3_DELETES",
    "RESTORED",
    "BuildError",
    "Change",
    "apply_patch3",
    "build_trees",
    "diff_trees",
    "tree_files",
]

#: Data-root directory holding one game tree per build and the manifest.
BUILDS_DIR = "builds"
MANIFEST_NAME = "patch3-manifest.json"
BuildName = Literal["unpatched", "patched"]
BUILD_NAMES: tuple[BuildName, ...] = ("unpatched", "patched")

#: What ``PATSI.BAT`` deletes, in its order (``DEL`` at the root, then ``CD RES``).
PATCH3_DELETES: tuple[str, ...] = (
    "GAME.CFG",
    "INSTALL.EXE",
    "INSTALL.CFG",
    "STUNT.EXE",
    "MAKEONE.EXE",
    "PLAYONE.EXE",
    "RES/MUSIC1.ESS",
    "RES/MUSIC2.ESS",
    "RES/SPRITES.RES",
    "RES/COMMNSND.SMP",
    "RES/SNDFX2.SMP",
)
#: What ``PATSI.BAT`` then runs with ``-d`` (extract with directories), in its order.
PATCH3_ARCHIVES: tuple[str, ...] = (
    "P3-SI1.EXE",
    "P3-SI2.EXE",
    "P3-SI3.EXE",
    "P3-SI4.EXE",
    "P3-SI5.EXE",
)
#: Files the patch deletes and its ``SETUP`` step would write again, kept from the shipped tree.
RESTORED: tuple[str, ...] = ("GAME.CFG",)

Action = Literal["added", "replaced", "deleted", "restored"]


class BuildError(RuntimeError):
    """The corpus or the patch is not what the build expects."""


@dataclass(frozen=True)
class Change:
    """One file the patched tree differs in from the unpatched one (DOS path, ``/``-separated)."""

    path: str
    action: Action
    old_bytes: int | None = None
    old_sha256: str | None = None
    new_bytes: int | None = None
    new_sha256: str | None = None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dos_name(name: str) -> str:
    """A zip member name as an upper-case relative DOS path ([I8]); refuses one that escapes."""
    pure = PurePosixPath(name.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise BuildError(f"archive member {name!r} is not a relative path inside the tree")
    return "/".join(part.upper() for part in pure.parts)


def _find(directory: Path, relative: str) -> Path | None:
    """*relative* under *directory*, matching each component without regard to case (DOS)."""
    here = directory
    for part in relative.split("/"):
        if not here.is_dir():
            return None
        match = next((c for c in here.iterdir() if c.name.upper() == part.upper()), None)
        if match is None:
            return None
        here = match
    return here


def tree_files(root: Path) -> dict[str, Path]:
    """Every file under *root*, keyed by its upper-case ``/``-separated path."""
    return {
        "/".join(p.relative_to(root).parts).upper(): p
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def apply_patch3(tree: Path, patch_dir: Path) -> None:
    """Apply Patch #3 to *tree* in place, as ``PATSI.BAT`` does, then restore :data:`RESTORED`.

    ``PATSI.BAT`` ignores a missing file (``DEL`` only warns) but refuses to start without
    ``STUNT.EXE`` or any of the five archives, so this does too. *tree* must be a copy.
    """
    if _find(tree, "STUNT.EXE") is None:
        raise BuildError(f"{tree} has no STUNT.EXE (PATSI.BAT refuses such a directory)")
    archives = []
    for name in PATCH3_ARCHIVES:
        found = _find(patch_dir, name)
        if found is None:
            raise BuildError(f"{patch_dir} has no {name} (PATSI.BAT needs all five)")
        archives.append(found)
    kept = {name: found.read_bytes() for name in RESTORED if (found := _find(tree, name))}
    for name in PATCH3_DELETES:
        found = _find(tree, name)
        if found is not None:
            found.unlink()
    for archive in archives:
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                if member.is_dir():
                    continue
                relative = _dos_name(member.filename)
                existing = _find(tree, relative)
                target = existing if existing is not None else tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zipped.read(member))
    for name, data in kept.items():
        if _find(tree, name) is None:
            (tree / name).write_bytes(data)


def diff_trees(before: Path, after: Path) -> list[Change]:
    """Every file added, replaced or deleted going from *before* to *after*, by path.

    A file that is identical in both is no change; :data:`RESTORED` files are listed as
    ``restored`` because the patch deleted them and the build put them back.
    """
    old, new = tree_files(before), tree_files(after)
    changes: list[Change] = []
    for path in sorted(old.keys() | new.keys()):
        o, n = old.get(path), new.get(path)
        o_sha = _sha256(o) if o else None
        n_sha = _sha256(n) if n else None
        if path in RESTORED:
            action: Action = "restored"
        elif o is None:
            action = "added"
        elif n is None:
            action = "deleted"
        elif o_sha != n_sha:
            action = "replaced"
        else:
            continue
        changes.append(
            Change(
                path=path,
                action=action,
                old_bytes=o.stat().st_size if o else None,
                old_sha256=o_sha,
                new_bytes=n.stat().st_size if n else None,
                new_sha256=n_sha,
            )
        )
    return changes


def _replace_dir(staging: Path, final: Path) -> None:
    """Move the finished *staging* tree to *final*, dropping whatever build was there."""
    if final.exists():
        shutil.rmtree(final)
    staging.rename(final)


def build_trees(game: Path, patch_dir: Path, out: Path) -> dict[str, Any]:
    """Build ``out/unpatched`` and ``out/patched`` from *game* and *patch_dir*; return the manifest.

    *game* and *patch_dir* are only read. Each tree is assembled under ``out/.<name>.partial``
    and renamed into place, so an interrupted run never leaves a half-built tree under its
    final name. The manifest is written to ``out/`` last.
    """
    if not (game / "PLAYONE.EXE").is_file():
        raise BuildError(f"{game} is not a game tree (no PLAYONE.EXE)")
    # Both the literal and the resolved paths: the corpus folders are links into the data root.
    targets = {out.absolute(), out.resolve()}
    for source in (game, patch_dir):
        for root in {source.absolute(), source.resolve()}:
            if any(t.is_relative_to(root) or root.is_relative_to(t) for t in targets):
                raise BuildError(f"{out} overlaps {source}, which is only read (ADR 0022)")
    out.mkdir(parents=True, exist_ok=True)
    partial = {name: out / f".{name}.partial" for name in BUILD_NAMES}
    for path in partial.values():
        shutil.rmtree(path, ignore_errors=True)
    try:
        shutil.copytree(game, partial["unpatched"])
        shutil.copytree(game, partial["patched"])
        apply_patch3(partial["patched"], patch_dir)
        changes = diff_trees(partial["unpatched"], partial["patched"])
    except BaseException:
        for path in partial.values():
            shutil.rmtree(path, ignore_errors=True)
        raise
    for name in BUILD_NAMES:
        _replace_dir(partial[name], out / name)
    manifest: dict[str, Any] = {
        "patch": "Disney Software Sound Blaster Update, Stunt Island Patch #3 (PATSI.BAT)",
        "source": game.name,
        "archives": {
            name: {"bytes": found.stat().st_size, "sha256": _sha256(found)}
            for name in PATCH3_ARCHIVES
            if (found := _find(patch_dir, name)) is not None
        },
        "restored": list(RESTORED),
        "changes": [asdict(change) for change in changes],
    }
    (out / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
