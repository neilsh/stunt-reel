"""Seed a new checkout's ``target/`` by cloning a donor checkout's build output.

Cargo finds a unit fresh from its fingerprint and its outputs' modification times, so a copy that
keeps both leaves every dependency fresh in another checkout, provided both name the shared cargo
cache by the same path: a different ``CARGO_HOME`` path alone rebuilds every dependency. A unit
of the checkout's own crates keeps its fingerprint only where every file it was built from
matches the donor's, and rebuilds otherwise (``prune_member_fingerprints``). On ReFS the copy
clones blocks instead of writing them, so a
seeded ``target/`` costs little disk. See
[ADR 0030](../../docs/adr/0030-new-worktrees-seed-target-by-block-clone.md) and the plan
``work/2026-11/target-seeding/spec.md``.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Literal

from stunt_reel.dataroot import is_link

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

#: The target directories a seed copies, in copy order: the gate's build, clippy and matrix lanes.
SEEDED_DIRS: tuple[str, ...] = ("debug", "check", "matrix")
#: Files at the top of target/ that a seed copies after the directories.
SEEDED_FILES: tuple[str, ...] = (".rustc_info.json", "CACHEDIR.TAG")
#: Where under target/ a seed assembles each copy before moving it into place.
STAGING = ".seeding"

#: How much of a dep-info file is read looking for a registry source path.
_DEP_INFO_BYTES = 4096
_REGISTRY_MARKERS = ("\\registry\\src\\", "/registry/src/")
#: The dep-info line prefix rustc writes for an environment variable a crate read at compile time.
_ENV_DEP = "# env-dep:"


def _norm(path: str | Path) -> str:
    """A path in one spelling: backslashes, no trailing separator, case-folded."""
    return str(path).replace("/", "\\").rstrip("\\").casefold()


#: The build directories that mean *target* has been built: the seeded ones, and ``release``,
#: which ``frame``, ``parity`` and ``sod-census`` build alone. No seed copies ``release``.
_BUILT_DIRS: tuple[str, ...] = (*SEEDED_DIRS, "release")


def needs_seed(target: Path) -> bool:
    """Whether *target* holds no build directory yet."""
    return not any((target / name).exists() for name in _BUILT_DIRS)


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
    names a registry source decides. Cargo 1.100 writes dep-info to ``build/<package>/<hash>/out/``,
    older Cargo to ``deps/``; both are read.
    """
    wanted = _norm(cargo_home)
    debug = target / "debug"
    dep_infos = [*(debug / "deps").glob("*.d"), *(debug / "build").glob("*/*/out/*.d")]
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
    cannot be read or names no package, and ``TypeError`` when ``workspace.members`` is not a
    list: a seed that missed a member would keep its fingerprints.
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
        raise TypeError(f"{root}: workspace.members is not a list")
    pending.extend(
        member for pattern in patterns for member in checkout.glob(f"{pattern}/Cargo.toml")
    )
    while pending:
        manifest = pending.pop()
        if _norm(manifest.resolve()) not in seen:
            seen.add(_norm(manifest.resolve()))
            visit(manifest, package=True)
    return frozenset(names)


def _unit_sources(dep_info: Path, donor: Path) -> list[str] | None:
    """The workspace-relative files rustc read to build a unit, from its dep-info *dep_info*.

    ``None`` when the unit cannot be reused: the file is unreadable or names no source, a source
    is absolute, or a recorded environment value holds *donor*'s path.
    """
    try:
        text = dep_info.read_text(encoding="utf-8")
    except OSError, ValueError:
        return None
    donor_path = _norm(donor)
    sources: list[str] = []
    for line in text.splitlines():
        if line.startswith(_ENV_DEP):
            # rustc doubles each backslash in an env-dep value.
            if donor_path in _norm(line.removeprefix(_ENV_DEP).replace("\\\\", "\\")):
                return None
            continue
        # Each source appears once more as a phony rule of its own: a line ending in a colon.
        if line.startswith("#") or not line.endswith(":"):
            continue
        source = line[:-1].replace("\\ ", " ")
        if source.startswith(("/", "\\")) or os.path.splitdrive(source)[0]:
            return None
        sources.append(source)
    return sources or None


def _member_units(seeded: Path, members: frozenset[str]) -> Iterator[tuple[Path, list[Path]]]:
    """Each unit of *members* in the copied directory *seeded*: its fingerprint directory and
    the rustc dep-info files that carry its hash.

    Cargo 1.100 keeps a unit in ``build/<package>/<hash>/``, its fingerprint in ``fingerprint/``
    and its dep-info in ``out/``; older Cargo kept ``.fingerprint/<package>-<hash>/`` and
    ``deps/``. A copy can hold both.
    """
    flat = re.compile("(?:" + "|".join(map(re.escape, sorted(members))) + r")-([0-9a-f]{16})")
    for profile in (seeded, *(entry for entry in seeded.iterdir() if entry.is_dir())):
        fingerprints = profile / ".fingerprint"
        if fingerprints.is_dir():
            for entry in fingerprints.iterdir():
                if match := flat.fullmatch(entry.name):
                    yield entry, list((profile / "deps").glob(f"*-{match[1]}.d"))
        for member in sorted(members):
            for fingerprint in (profile / "build" / member).glob("*/fingerprint"):
                unit = fingerprint.parent
                yield fingerprint, list((unit / "out").glob(f"*-{unit.name}.d"))


def _names_donor(fingerprint: Path, donor: Path) -> bool:
    """Whether a file in the unit's fingerprint directory *fingerprint* holds *donor*'s path.

    Cargo records a file outside the package, such as a fixture read by ``include_bytes!`` or
    clippy's ``clippy.toml``, by its absolute path, so a copied unit would watch the donor's file.
    """
    wanted = {_norm(donor), _norm(os.path.realpath(donor))}
    try:
        held = [entry.read_bytes() for entry in fingerprint.iterdir() if entry.is_file()]
    except OSError:
        return True
    texts = [_norm(data.decode("utf-8", "replace")) for data in held]
    return any(path in text for text in texts for path in wanted)


def _reusable_unit(
    fingerprint: Path, dep_infos: list[Path], *, donor: Path, checkout: Path
) -> list[tuple[Path, os.stat_result]] | None:
    """*checkout*'s files the unit *fingerprint* was built from, each with *donor*'s stat.

    ``None`` unless *dep_infos*, the unit's rustc dep-info files, is exactly one, no file in
    *fingerprint* holds *donor*'s path, and every file the dep-info names is byte-identical in
    both checkouts and unchanged while read.
    """
    if len(dep_infos) != 1 or _names_donor(fingerprint, donor):
        return None
    sources = _unit_sources(dep_infos[0], donor)
    if sources is None:
        return None
    stamps: list[tuple[Path, os.stat_result]] = []
    for source in sources:
        theirs, ours = donor / source, checkout / source
        try:
            before = theirs.stat()
            same = theirs.read_bytes() == ours.read_bytes()
            after = theirs.stat()
        except OSError:
            return None
        if not same or before.st_mtime_ns != after.st_mtime_ns:
            return None
        stamps.append((ours, before))
    return stamps


def prune_member_fingerprints(
    seeded: Path, members: frozenset[str], *, donor: Path, checkout: Path
) -> None:
    """Delete the fingerprints of *members*' units under the copied directory *seeded*, except
    those whose sources are byte-identical in *checkout* and *donor*.

    Cargo calls a workspace unit fresh when its sources are older than its outputs, whatever they
    hold, so a unit that may differ from the donor's must rebuild. A kept unit's sources take the
    donor's modification times, so Cargo judges it here as it would in *donor*.
    """
    if not members:
        return
    # Listed before any deletion, which would otherwise change the directories being walked.
    for fingerprint, dep_infos in list(_member_units(seeded, members)):
        stamps = _reusable_unit(fingerprint, dep_infos, donor=donor, checkout=checkout)
        if stamps is None:
            shutil.rmtree(fingerprint)
            continue
        for path, stat in stamps:
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))


#: Where a profile keeps its units' fingerprints: ``build/`` since Cargo 1.100, ``.fingerprint/``
#: before.
_FINGERPRINT_DIRS: tuple[str, ...] = ("build", ".fingerprint")


def _last_build(target: Path) -> float | None:
    """The newest modification time of *target*'s debug fingerprint directories, or ``None``
    when it has none: *target* was never built."""
    times = [
        _mtime(target / "debug" / name)
        for name in _FINGERPRINT_DIRS
        if (target / "debug" / name).is_dir()
    ]
    return max(times) if times else None


def donor_problem(checkout: Path, *, rustc_vv: str, cargo_home: Path) -> str | None:
    """Why *checkout*'s target/ cannot seed another, or ``None`` when it can."""
    target = checkout / "target"
    if _last_build(target) is None:
        return "not built"
    if not built_by(target, rustc_vv):
        return "built by another rustc"
    if not uses_cargo_home(target, cargo_home):
        return "built against another cargo home"
    return None


def _head(checkout: Path) -> str | None:
    """The commit *checkout* has checked out, or ``None`` when git cannot say."""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv
            [git, "-C", str(checkout), "rev-parse", "--verify", "--quiet", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    head = result.stdout.strip()
    return head if result.returncode == 0 and head else None


def _newest_file(directory: Path) -> float | None:
    """The newest modification time of the files directly in *directory*, or ``None``."""
    newest: float | None = None
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                if is_link(path) or not entry.is_file(follow_symlinks=False):
                    continue
                try:
                    stamp = entry.stat(follow_symlinks=False).st_mtime
                except OSError:
                    continue
                newest = stamp if newest is None else max(newest, stamp)
    except OSError:
        return None
    return newest


def _unit_dirs(directory: Path) -> list[Path]:
    """The immediate subdirectories of *directory*, never a link, so a walk cannot leave it."""
    try:
        with os.scandir(directory) as entries:
            return [
                Path(entry.path)
                for entry in entries
                if entry.is_dir(follow_symlinks=False) and not is_link(Path(entry.path))
            ]
    except OSError:
        return []


def _build_recency(target: Path) -> float | None:
    """The newest mtime of the files Cargo rewrites on every build, or ``None``.

    Cargo 1.100 writes each unit's ``fingerprint/`` under ``debug/build/<package>/<hash>/``;
    older Cargo wrote ``debug/.fingerprint/<package>-<hash>/``. Reading those files, one level
    of unit directories at a time, tells a real build apart from a seeded copy: a block clone
    keeps the donor's directory times (issue #521).
    """
    debug = target / "debug"
    stamps = [
        stamp
        for package in _unit_dirs(debug / "build")
        for unit in _unit_dirs(package)
        if (stamp := _newest_file(unit / "fingerprint")) is not None
    ]
    stamps += [
        stamp
        for unit in _unit_dirs(debug / ".fingerprint")
        if (stamp := _newest_file(unit)) is not None
    ]
    return max(stamps) if stamps else None


def rank_donors(
    checkouts: Sequence[Path], *, here: Path, rustc_vv: str, cargo_home: Path
) -> list[Path]:
    """The checkouts whose target/ can seed *here*'s, best first.

    A donor must be another existing checkout whose target/ was built by the same compiler against
    the same cargo cache. One whose ``HEAD`` is *here*'s commit ranks first, since its member units
    need no rebuild; then one with *here*'s exact ``Cargo.lock``, since no dependency rebuilds; ties
    go to the most recent build, read from the fingerprint files Cargo rewrites rather than a
    block-cloned directory's time (issue #521).
    """
    own = _norm(here.resolve())
    head = _head(here)
    try:
        lock = (here / "Cargo.lock").read_bytes()
    except OSError:
        lock = None
    ranked: list[tuple[bool, bool, float, Path]] = []
    for checkout in checkouts:
        if _norm(checkout.resolve()) == own:
            continue
        if donor_problem(checkout, rustc_vv=rustc_vv, cargo_home=cargo_home) is not None:
            continue
        try:
            same_lock = lock is not None and (checkout / "Cargo.lock").read_bytes() == lock
        except OSError:
            same_lock = False
        same_head = head is not None and _head(checkout) == head
        ranked.append((same_head, same_lock, _build_recency(checkout / "target") or 0.0, checkout))
    ranked.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    return [checkout for _, _, _, checkout in ranked]


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
    with contextlib.ExitStack() as held:
        for seeded in SEEDED_DIRS:
            for profile, name in ((p, n) for p in _LOCK_DIRS for n in _BUILD_LOCKS):
                lock = target / seeded / profile / name
                if lock.is_file() and not _hold(held, lock):
                    yield False
                    return
        yield True


def _hold(held: contextlib.ExitStack, lock: Path) -> bool:
    """Take Cargo's lock file *lock* until *held* closes; false if it is held or cannot be opened.

    A lock this session cannot open or take counts as held: the donor is passed over, and the
    next one tried.
    """
    try:
        handle = held.enter_context(lock.open("r+b"))
        if not _try_lock(handle):
            return False
    except OSError:
        return False
    held.callback(_unlock, handle)
    return True


#: The errors a lock call raises because another handle holds the lock; any other is raised.
# EDEADLK, not its alias EDEADLOCK, which macOS does not define; msvcrt raises the same value.
_CONTENTION = frozenset({errno.EDEADLK, errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK})


@contextlib.contextmanager
def exclusive(path: Path, *, timeout: float = 600.0) -> Iterator[None]:
    """Hold an exclusive OS lock on the file *path*, created if missing, for the block.

    Waits up to *timeout* seconds while another handle holds it, then raises ``TimeoutError``
    (a seed takes about 40 s, so the default means a stuck holder); any other lock failure is
    raised at once. Each call opens its own handle, so threads of one process exclude each
    other as processes do (ADR 0036).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with path.open("a+b") as handle:
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{path} still locked after {timeout:.0f} s")
            time.sleep(0.2)
        try:
            yield
        finally:
            _unlock(handle)


def _try_lock(handle: BinaryIO) -> bool:
    """Take a one-byte lock at the start of *handle* without waiting; false while another holds it.

    The one place that knows each platform's call: ``msvcrt`` on Windows, ``flock`` elsewhere.
    Any failure but contention is raised.
    """
    try:
        if sys.platform == "win32":
            import msvcrt  # noqa: PLC0415 - only needed on Windows

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl  # noqa: PLC0415 - only needed off Windows

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno in _CONTENTION:
            return False
        raise
    return True


def _unlock(handle: BinaryIO) -> None:
    """Release the lock :func:`_try_lock` took on *handle*."""
    if sys.platform == "win32":
        import msvcrt  # noqa: PLC0415 - only needed on Windows

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl  # noqa: PLC0415 - only needed off Windows

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
    except (OSError, ValueError, TypeError) as error:
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

    The copy keeps a fingerprint of *members*, the checkout's own crates, only where the unit's
    sources match the donor's (``prune_member_fingerprints``).
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
                prune_member_fingerprints(
                    staging / name, members, donor=donor, checkout=target.parent
                )
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
