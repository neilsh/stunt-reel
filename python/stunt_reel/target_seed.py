"""Seed a new checkout's ``target/`` by cloning a donor checkout's build output.

Cargo finds a unit fresh from its fingerprint and its outputs' modification times, so a copy that
keeps both is fresh in another checkout, provided both name the shared cargo cache by the same
path: a different ``CARGO_HOME`` path alone rebuilds every dependency. On ReFS the copy clones
blocks instead of writing them, so a seeded ``target/`` costs little disk. See
[ADR 0030](../../docs/adr/0030-new-worktrees-seed-target-by-block-clone.md) and the plan
``docs/process/plans/target-seeding-2026-11-02.md``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

#: The target directories a seed copies, in copy order: the gate's build, clippy and matrix lanes.
SEEDED_DIRS: tuple[str, ...] = ("debug", "check", "matrix")
#: Files at the top of target/ that a seed copies after the directories.
SEEDED_FILES: tuple[str, ...] = (".rustc_info.json", "CACHEDIR.TAG")

#: How much of a dep-info file is read looking for a registry source path.
_DEP_INFO_BYTES = 4096
_REGISTRY_MARKERS = ("\\registry\\src\\", "/registry/src/")


def _norm(path: str | Path) -> str:
    """A path in one spelling: backslashes, no trailing separator, case-folded."""
    return str(path).replace("/", "\\").rstrip("\\").casefold()


def needs_seed(target: Path) -> bool:
    """Whether *target* holds none of the seeded build directories yet."""
    return not any((target / name).exists() for name in SEEDED_DIRS)


def built_by(target: Path, rustc_vv: str) -> bool:
    """Whether Cargo recorded *rustc_vv* (``rustc -vV``) as the compiler that built *target*."""
    try:
        info = json.loads((target / ".rustc_info.json").read_text(encoding="utf-8"))
        outputs = info["outputs"].values()
        return any(str(entry.get("stdout", "")).strip() == rustc_vv.strip() for entry in outputs)
    except OSError, ValueError, KeyError, AttributeError, TypeError:
        return False


def uses_cargo_home(target: Path, cargo_home: Path) -> bool:
    """Whether *target*'s dependencies were built from the registry under *cargo_home*."""
    wanted = _norm(cargo_home)
    for dep_info in sorted((target / "debug" / "deps").glob("*.d")):
        try:
            with dep_info.open(encoding="utf-8", errors="replace") as handle:
                head = handle.read(_DEP_INFO_BYTES)
        except OSError:
            continue
        for token in head.split():
            for marker in _REGISTRY_MARKERS:
                if marker in token:
                    return _norm(token.split(marker, 1)[0]) == wanted
    return False


def rank_donors(
    checkouts: Sequence[Path], *, here: Path, rustc_vv: str, cargo_home: Path
) -> list[Path]:
    """The checkouts whose target/ can seed *here*'s, best first.

    A donor must be another existing checkout whose target/ was built by the same compiler against
    the same cargo cache. One with *here*'s exact ``Cargo.lock`` ranks above one without, since
    then nothing rebuilds; ties go to the most recent build.
    """
    own = _norm(here.resolve())
    try:
        lock = (here / "Cargo.lock").read_bytes()
    except OSError:
        lock = None
    ranked: list[tuple[bool, float, Path]] = []
    for checkout in checkouts:
        target = checkout / "target"
        fingerprint = target / "debug" / ".fingerprint"
        if not checkout.is_dir() or _norm(checkout.resolve()) == own:
            continue
        if not fingerprint.is_dir():
            continue
        if not built_by(target, rustc_vv) or not uses_cargo_home(target, cargo_home):
            continue
        try:
            same_lock = lock is not None and (checkout / "Cargo.lock").read_bytes() == lock
        except OSError:
            same_lock = False
        ranked.append((same_lock, fingerprint.stat().st_mtime, checkout))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [checkout for _, _, checkout in ranked]
