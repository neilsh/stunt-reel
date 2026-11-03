"""Seed a new checkout's ``target/`` by cloning a donor checkout's build output.

Cargo finds a unit fresh from its fingerprint and its outputs' modification times, so a copy that
keeps both leaves every dependency fresh in another checkout, provided both name the shared cargo
cache by the same path: a different ``CARGO_HOME`` path alone rebuilds every dependency. The
checkout's own crates always rebuild, because the seed drops their fingerprints
(``drop_member_fingerprints``). On ReFS the copy clones blocks instead of writing them, so a
seeded ``target/`` costs little disk. See
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
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

#: The target directories a seed copies, in copy order: the gate's build, clippy and matrix lanes.
SEEDED_DIRS: tuple[str, ...] = ("debug", "check", "matrix")
#: Files at the top of target/ that a seed copies after the directories.
SEEDED_FILES: tuple[str, ...] = (".rustc_info.json", "CACHEDIR.TAG")
#: Where under target/ a seed assembles each copy before moving it into place.
STAGING = ".seeding"

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
        # rustc writes a space inside a dep-info path as a backslash-space.
        for escaped in head.replace("\\ ", "\0").split():
            token = escaped.replace("\0", " ")
            for marker in _REGISTRY_MARKERS:
                if marker in token:
                    return _norm(token.split(marker, 1)[0]) == wanted
    return False


#: The manifest tables, at the top level or under ``[target.<cfg>]``, that name dependencies.
_DEPENDENCY_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")


def _path_dependencies(manifest: dict[str, object]) -> Iterator[str]:
    """The ``path`` of every dependency, workspace dependency and patch *manifest* declares."""
    tables = [manifest.get(name) for name in _DEPENDENCY_TABLES]
    platforms = manifest.get("target")
    if isinstance(platforms, dict):
        tables += [
            platform.get(name)
            for platform in platforms.values()
            if isinstance(platform, dict)
            for name in _DEPENDENCY_TABLES
        ]
    workspace = manifest.get("workspace")
    if isinstance(workspace, dict):
        tables.append(workspace.get("dependencies"))
    patches = manifest.get("patch")
    if isinstance(patches, dict):
        tables += patches.values()
    for table in tables:
        if isinstance(table, dict):
            for spec in table.values():
                if isinstance(spec, dict) and isinstance(spec.get("path"), str):
                    yield spec["path"]


def workspace_members(checkout: Path) -> frozenset[str]:
    """The package names of *checkout*'s Cargo workspace and every path dependency it reaches.

    Cargo fingerprints a path dependency the way it does a member, by its sources' times, and
    makes one under the workspace root a member without listing it; so both count.

    Raises ``OSError`` or ``ValueError`` (``tomllib.TOMLDecodeError`` is one) when a manifest
    cannot be read or names no package: a seed that missed a member would keep its fingerprints.
    """
    names: set[str] = set()
    seen: set[str] = set()
    pending: list[Path] = []

    def visit(path: Path, *, package: bool) -> dict[str, object]:
        manifest = tomllib.loads(path.read_text(encoding="utf-8"))
        if package or "package" in manifest:
            table = manifest.get("package")
            name = table.get("name") if isinstance(table, dict) else None
            if not isinstance(name, str) or not name:
                raise ValueError(f"{path} names no package")
            names.add(name)
        pending.extend(path.parent / found / "Cargo.toml" for found in _path_dependencies(manifest))
        return manifest

    root = checkout / "Cargo.toml"
    seen.add(_norm(root.resolve()))
    workspace = visit(root, package=False).get("workspace", {})
    patterns = workspace.get("members", []) if isinstance(workspace, dict) else None
    if not isinstance(patterns, list):
        raise ValueError(f"{root}: workspace.members is not a list")
    pending.extend(
        member for pattern in patterns for member in checkout.glob(f"{pattern}/Cargo.toml")
    )
    while pending:
        manifest = pending.pop()
        if _norm(manifest.resolve()) not in seen:
            seen.add(_norm(manifest.resolve()))
            visit(manifest, package=True)
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


def donor_problem(checkout: Path, *, rustc_vv: str, cargo_home: Path) -> str | None:
    """Why *checkout*'s target/ cannot seed another, or ``None`` when it can."""
    target = checkout / "target"
    if not (target / "debug" / ".fingerprint").is_dir():
        return "not built"
    if not built_by(target, rustc_vv):
        return "built by another rustc"
    if not uses_cargo_home(target, cargo_home):
        return "built against another cargo home"
    return None


def rank_donors(
    checkouts: Sequence[Path], *, here: Path, rustc_vv: str, cargo_home: Path
) -> list[Path]:
    """The checkouts whose target/ can seed *here*'s, best first.

    A donor must be another existing checkout whose target/ was built by the same compiler against
    the same cargo cache. One with *here*'s exact ``Cargo.lock`` ranks above one without, since
    then no dependency rebuilds; ties go to the most recent build.
    """
    own = _norm(here.resolve())
    try:
        lock = (here / "Cargo.lock").read_bytes()
    except OSError:
        lock = None
    ranked: list[tuple[bool, float, Path]] = []
    for checkout in checkouts:
        fingerprint = checkout / "target" / "debug" / ".fingerprint"
        if _norm(checkout.resolve()) == own:
            continue
        if donor_problem(checkout, rustc_vv=rustc_vv, cargo_home=cargo_home) is not None:
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
                    # A lock this session cannot open or take counts as held: the donor is
                    # passed over, and the next one tried.
                    try:
                        handle = held.enter_context(lock.open("r+b"))
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
    # What a killed seed left half-built; it never counts as built, so clear it whatever happens.
    shutil.rmtree(target / STAGING, ignore_errors=True)
    if not needs_seed(target):
        return SeedOutcome("skipped", "target/ already built")
    if not volume_clones(checkout):
        return SeedOutcome("skipped", "volume does not clone blocks")
    drive = os.path.splitdrive(str(checkout))[0].casefold()
    local = [other for other in checkouts if os.path.splitdrive(str(other))[0].casefold() == drive]
    donors = rank_donors(local, here=checkout, rustc_vv=rustc_vv, cargo_home=cargo_home)
    if not donors:
        own = _norm(checkout.resolve())
        reasons = Counter(
            "on another drive"
            if other not in local
            else donor_problem(other, rustc_vv=rustc_vv, cargo_home=cargo_home) or "usable"
            for other in checkouts
            if _norm(other.resolve()) != own
        )
        why = ", ".join(f"{count} {reason}" for reason, count in sorted(reasons.items()))
        return SeedOutcome("skipped", f"no donor: {why or 'no other checkout'}")
    try:
        members = workspace_members(checkout)
    except (OSError, ValueError) as error:
        return SeedOutcome("skipped", f"cannot read the workspace members: {error}")
    if not members:
        return SeedOutcome("skipped", "cannot read the workspace members: none found")
    busy: list[Path] = []
    rebuilt = 0
    for donor in donors:
        with build_locks_free(donor / "target") as free:
            if not free:
                busy.append(donor)
                continue
            # Ranking read the donor before its locks were held; a build in between may have
            # changed its rustc or cargo home, so check again now that none can start.
            if donor_problem(donor, rustc_vv=rustc_vv, cargo_home=cargo_home) is not None:
                rebuilt += 1
                continue
            lanes = [
                name
                for name in SEEDED_DIRS
                if name == "debug" or fresh_lane(donor / "target" / name, rustc_vv, cargo_home)
            ]
            outcome = _copy_from(donor, target, copy, members, lanes)
            stale = [
                name
                for name in SEEDED_DIRS
                if name not in lanes and (donor / "target" / name).is_dir()
            ]
            if outcome.status == "seeded" and stale:
                return SeedOutcome("seeded", f"{outcome.detail} (not its stale {', '.join(stale)})")
            return outcome
    if rebuilt:
        return SeedOutcome(
            "skipped", f"no donor: {len(busy)} building, {rebuilt} rebuilt since ranked"
        )
    if len(busy) == 1:
        return SeedOutcome("skipped", f"donor {busy[0]} is building")
    return SeedOutcome("skipped", f"all {len(busy)} donors are building")


def fresh_lane(lane: Path, rustc_vv: str, cargo_home: Path) -> bool:
    """Whether the gate lane's own target directory *lane* (``target/check``, ``target/matrix``)
    was last built by this rustc against this cargo cache; one that was not would only rebuild."""
    return built_by(lane, rustc_vv) and uses_cargo_home(lane, cargo_home)


def _copy_from(
    donor: Path,
    target: Path,
    copy: Callable[[Path, Path], None],
    members: frozenset[str],
    lanes: Sequence[str],
) -> SeedOutcome:
    """Copy *donor*'s *lanes* and seeded files into *target*, undoing all of it on failure.

    The copy keeps no fingerprint of *members*, the checkout's own crates: they always rebuild.
    Each directory is copied and stripped of them under ``target/.seeding`` and only then moved
    into place, so a seed stopped part way (Ctrl-C, a killed process) never leaves a directory
    that holds them and that ``needs_seed`` would count as built.
    """
    staging = target / STAGING
    moved: list[Path] = []
    try:
        for name in lanes:
            source = donor / "target" / name
            if source.is_dir():
                copy(source, staging / name)
                drop_member_fingerprints(staging / name, members)
                (staging / name).rename(target / name)
                moved.append(target / name)
        for name in SEEDED_FILES:
            source = donor / "target" / name
            if source.is_file() and not (target / name).exists():
                staging.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, staging / name)
                (staging / name).rename(target / name)
                moved.append(target / name)
        _remove(staging)
    except BaseException as error:  # an interrupt is cleaned up too, then re-raised
        stuck = [str(path) for path in (*moved, staging) if not _remove(path)]
        if not isinstance(error, Exception):
            raise
        # A seed must never fail init: any other error becomes the line init prints.
        left = f"; could not remove {', '.join(stuck)}" if stuck else ""
        return SeedOutcome("failed", f"{error}{left}")
    return SeedOutcome("seeded", f"from {donor}")


def _remove(path: Path) -> bool:
    """Delete the file or tree *path*; whether it is gone."""
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
    return not path.exists()
