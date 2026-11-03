"""Seed a new checkout's ``target/`` by cloning a donor checkout's build output.

Cargo finds a unit fresh from its fingerprint and its outputs' modification times, so a copy that
keeps both is fresh in another checkout, provided both name the shared cargo cache by the same
path: a different ``CARGO_HOME`` path alone rebuilds every dependency. On ReFS the copy clones
blocks instead of writing them, so a seeded ``target/`` costs little disk. See
[ADR 0030](../../docs/adr/0030-new-worktrees-seed-target-by-block-clone.md) and the plan
``docs/process/plans/target-seeding-2026-11-02.md``.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
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


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def uses_cargo_home(target: Path, cargo_home: Path) -> bool:
    """Whether *target*'s latest dependency build used the registry under *cargo_home*.

    A target/ once built with another cache keeps those dep-info files, so the newest one that
    names a registry source decides.
    """
    wanted = _norm(cargo_home)
    dep_infos = (target / "debug" / "deps").glob("*.d")
    for dep_info in sorted(dep_infos, key=_mtime, reverse=True):
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


def workspace_members(checkout: Path) -> frozenset[str]:
    """The package names of *checkout*'s Cargo workspace; empty when it has none."""
    try:
        manifest = tomllib.loads((checkout / "Cargo.toml").read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return frozenset()
    names: set[str] = set()
    if isinstance(manifest.get("package"), dict):
        names.add(str(manifest["package"].get("name", "")))
    patterns = manifest.get("workspace", {}).get("members", [])
    for pattern in patterns if isinstance(patterns, list) else []:
        for member in checkout.glob(f"{pattern}/Cargo.toml"):
            try:
                package = tomllib.loads(member.read_text(encoding="utf-8")).get("package", {})
            except OSError, tomllib.TOMLDecodeError:
                continue
            names.add(str(package.get("name", "")))
    names.discard("")
    return frozenset(names)


def drop_member_fingerprints(seeded: Path, members: frozenset[str]) -> None:
    """Delete the fingerprints of *members*' units under the copied directory *seeded*.

    Cargo calls a workspace unit fresh when its sources are older than its outputs, whatever they
    hold, so a donor's build of the checkout's own crates could pass for this checkout's: it would
    run the donor's code and the donor's ``CARGO_MANIFEST_DIR``. Without a fingerprint Cargo
    rebuilds the unit; dependencies, named by registry path, keep theirs.
    """
    if not members:
        return
    unit = re.compile("(?:" + "|".join(map(re.escape, sorted(members))) + r")-[0-9a-f]{16}")
    for fingerprints in (seeded / ".fingerprint", *seeded.glob("*/.fingerprint")):
        if not fingerprints.is_dir():
            continue
        for entry in fingerprints.iterdir():
            if unit.fullmatch(entry.name):
                shutil.rmtree(entry)


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


#: Cargo's lock files in a profile directory; a build holds them while it writes.
_BUILD_LOCKS: tuple[str, ...] = (".cargo-lock", ".cargo-build-lock", ".cargo-artifact-lock")
#: Where under a seeded directory its profile's locks sit: ``debug/`` is itself the profile, while
#: the clippy and matrix lanes are whole target directories with a ``debug/`` profile inside.
_LOCK_DIRS: tuple[str, ...] = (".", "debug")
#: robocopy keeps file and directory timestamps (Cargo's freshness reads them) and never retries.
_ROBOCOPY_FLAGS: tuple[str, ...] = (
    "/E",
    "/COPY:DAT",
    "/DCOPY:DAT",
    "/R:0",
    "/W:0",
    "/NFL",
    "/NDL",
    "/NJH",
    "/NJS",
)
#: robocopy exit codes from this value up report a failure; below it, what was copied.
_ROBOCOPY_FAILED = 8


@dataclass(frozen=True)
class SeedOutcome:
    """What a seed did, for the one line ``init`` prints."""

    status: Literal["seeded", "skipped", "failed"]
    detail: str


def clones_on(path: Path) -> bool:
    """Whether *path*'s volume clones blocks on copy: ReFS, on Windows only."""
    # The Windows code sits in a platform branch that returns nothing, so mypy analysing for
    # either platform finds no unreachable statement.
    refs = False
    if sys.platform == "win32":
        import ctypes  # noqa: PLC0415 - only needed on Windows

        drive, _ = os.path.splitdrive(str(path.resolve()))
        name = ctypes.create_unicode_buffer(64)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            drive + "\\", None, 0, None, None, None, name, len(name)
        )
        refs = bool(ok) and name.value == "ReFS"
    return refs


@contextlib.contextmanager
def build_locks_free(target: Path) -> Iterator[bool]:
    """Hold every Cargo build lock under *target* for the copy; yield false if one is taken."""
    if sys.platform == "win32":
        import msvcrt  # noqa: PLC0415 - only needed on Windows

        with contextlib.ExitStack() as held:
            for seeded in SEEDED_DIRS:
                for profile, name in ((p, n) for p in _LOCK_DIRS for n in _BUILD_LOCKS):
                    lock = target / seeded / profile / name
                    if not lock.is_file():
                        continue
                    handle = held.enter_context(lock.open("r+b"))
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    except OSError:
                        yield False
                        return
                    held.callback(_unlock, handle)
            yield True
    else:
        yield True


def _unlock(handle: BinaryIO) -> None:
    """Release the one-byte lock ``build_locks_free`` took at the start of *handle*."""
    if sys.platform == "win32":
        import msvcrt  # noqa: PLC0415 - only needed on Windows

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def robocopy(source: Path, destination: Path) -> None:
    """Copy the tree *source* to *destination*, keeping timestamps; raise on a robocopy failure."""
    command = shutil.which("robocopy")
    if command is None:
        raise OSError("robocopy is not on PATH")
    result = subprocess.run(  # noqa: S603 - fixed argv, robocopy resolved from PATH
        [command, str(source), str(destination), *_ROBOCOPY_FLAGS],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode >= _ROBOCOPY_FAILED:
        raise OSError(f"robocopy {source} exited {result.returncode}: {result.stdout.strip()}")


def seed(
    checkout: Path,
    *,
    checkouts: Sequence[Path],
    rustc_vv: str,
    cargo_home: Path,
    copy: Callable[[Path, Path], None] = robocopy,
    volume_clones: Callable[[Path], bool] = clones_on,
) -> SeedOutcome:
    """Clone the best idle donor's build output into *checkout*'s empty target/.

    Best effort: anything that goes wrong after copying started removes what was copied, so a
    failed seed leaves the target/ as it found it and the next build starts from scratch.
    """
    target = checkout / "target"
    if not needs_seed(target):
        return SeedOutcome("skipped", "target/ already built")
    if not volume_clones(checkout):
        return SeedOutcome("skipped", "volume does not clone blocks")
    drive = os.path.splitdrive(str(checkout))[0].casefold()
    local = [other for other in checkouts if os.path.splitdrive(str(other))[0].casefold() == drive]
    donors = rank_donors(local, here=checkout, rustc_vv=rustc_vv, cargo_home=cargo_home)
    if not donors:
        return SeedOutcome("skipped", "no donor with this rustc and cargo home")
    busy: list[Path] = []
    for donor in donors:
        with build_locks_free(donor / "target") as free:
            if not free:
                busy.append(donor)
                continue
            return _copy_from(donor, target, copy, workspace_members(checkout))
    if len(busy) == 1:
        return SeedOutcome("skipped", f"donor {busy[0]} is building")
    return SeedOutcome("skipped", f"all {len(busy)} donors are building")


def _copy_from(
    donor: Path, target: Path, copy: Callable[[Path, Path], None], members: frozenset[str]
) -> SeedOutcome:
    """Copy *donor*'s seeded directories and files into *target*, undoing all of it on failure.

    The copy keeps no fingerprint of *members*, the checkout's own crates: they always rebuild.
    """
    created: list[Path] = []
    try:
        for name in SEEDED_DIRS:
            source = donor / "target" / name
            if source.is_dir():
                created.append(target / name)
                copy(source, target / name)
                drop_member_fingerprints(target / name, members)
        for name in SEEDED_FILES:
            source = donor / "target" / name
            if source.is_file() and not (target / name).exists():
                created.append(target / name)
                shutil.copy2(source, target / name)
    except Exception as error:  # noqa: BLE001 - a seed must never fail init
        for path in created:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        return SeedOutcome("failed", str(error))
    return SeedOutcome("seeded", f"from {donor}")
