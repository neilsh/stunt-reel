"""Seeding a new worktree's target/ from a donor checkout (ADR 0030)."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

import pytest

from stunt_reel import target_seed
from stunt_reel.target_seed import (
    SeedOutcome,
    built_by,
    clones_on,
    needs_seed,
    rank_donors,
    seed,
    uses_cargo_home,
    workspace_members,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.windows

RUSTC = "rustc 1.99.1 (58cf8f9c3 2026-10-13)\nhost: x86_64-pc-windows-msvc\n"
HOME = r"E:\git\stunt-reel\.cache\cargo"


def _donor(
    root: Path,
    *,
    rustc: str = RUSTC,
    home: str = HOME,
    lock: str = "a",
    age: float = 0,
    lanes: tuple[str, ...] = (),
) -> Path:
    """A checkout whose target/, and each gate lane in *lanes*, looks built by *rustc* against
    the registry under *home*."""
    target = root / "target"
    fingerprint = target / "debug" / ".fingerprint"
    fingerprint.mkdir(parents=True)
    (root / "Cargo.lock").write_text(lock, encoding="utf-8")
    for built in (target, *(target / lane for lane in lanes)):
        _built(built, rustc=rustc, home=home)
    stamp = time.time() - age
    os.utime(fingerprint, (stamp, stamp))
    return root


def _built(target: Path, *, rustc: str = RUSTC, home: str = HOME) -> None:
    """Cargo's record in the target directory *target* of a build by *rustc* against *home*."""
    deps = target / "debug" / "deps"
    deps.mkdir(parents=True, exist_ok=True)
    (target / ".rustc_info.json").write_text(
        json.dumps({"outputs": {"1": {"stdout": rustc}}}), encoding="utf-8"
    )
    source = home + r"\registry\src\index\serde_core\src\lib.rs"
    (deps / "serde_core-0123456789abcdef.d").write_text(
        f"{deps}\\serde_core-0123456789abcdef.d: {source}\n", encoding="utf-8"
    )


def test_needs_seed_ignores_tmp_log_and_doc(tmp_path: Path) -> None:
    for name in ("tmp", "doc"):
        (tmp_path / "target" / name).mkdir(parents=True)
    (tmp_path / "target" / "check.log").write_text("x", encoding="utf-8")
    assert needs_seed(tmp_path / "target")
    (tmp_path / "target" / "matrix").mkdir()
    assert not needs_seed(tmp_path / "target")


def test_needs_seed_when_target_absent(tmp_path: Path) -> None:
    assert needs_seed(tmp_path / "target")


def test_built_by_matches_rustc_and_tolerates_missing_info(tmp_path: Path) -> None:
    a = _donor(tmp_path / "a")
    assert built_by(a / "target", RUSTC)
    assert not built_by(a / "target", RUSTC.replace("1.99.1", "1.99.0"))
    (a / "target" / ".rustc_info.json").unlink()
    assert not built_by(a / "target", RUSTC)


def test_uses_cargo_home_normalizes_separators_and_case(tmp_path: Path) -> None:
    a = _donor(tmp_path / "a")
    assert uses_cargo_home(a / "target", Path("e:/GIT/stunt-reel/.cache/cargo/"))
    assert not uses_cargo_home(a / "target", Path(r"E:\packages\cargo"))


def test_uses_cargo_home_false_without_registry_dep_info(tmp_path: Path) -> None:
    a = _donor(tmp_path / "a")
    for dep_info in (a / "target" / "debug" / "deps").glob("*.d"):
        dep_info.unlink()
    assert not uses_cargo_home(a / "target", Path(HOME))


def test_rank_prefers_matching_lock_then_newest(tmp_path: Path) -> None:
    here = tmp_path / "here"
    here.mkdir()
    (here / "Cargo.lock").write_text("a", encoding="utf-8")
    old_same = _donor(tmp_path / "old", lock="a", age=600)
    new_same = _donor(tmp_path / "new", lock="a", age=10)
    newest_other = _donor(tmp_path / "other", lock="b", age=1)
    assert rank_donors(
        [old_same, newest_other, new_same], here=here, rustc_vv=RUSTC, cargo_home=Path(HOME)
    ) == [new_same, old_same, newest_other]


def test_rank_drops_self_missing_and_disqualified(tmp_path: Path) -> None:
    here = _donor(tmp_path / "here")
    wrong_rustc = _donor(tmp_path / "r", rustc="rustc 1.98.0\n")
    wrong_home = _donor(tmp_path / "h", home=r"E:\packages\cargo")
    good = _donor(tmp_path / "g")
    assert rank_donors(
        [here, tmp_path / "gone", wrong_rustc, wrong_home, good],
        here=here,
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
    ) == [good]


def _never(source: Path, destination: Path) -> None:
    raise AssertionError(f"copied {source} to {destination}")


def _clones(_: Path) -> bool:
    return True


def _fresh(root: Path, *members: str) -> Path:
    """An unbuilt checkout: a workspace of *members* (one crate by default) and a lockfile."""
    _workspace(root, *(members or ("stunt-core",)))
    (root / "Cargo.lock").write_text("a", encoding="utf-8")
    return root


def test_seed_copies_dirs_then_files_from_best_donor(tmp_path: Path) -> None:
    here = _fresh(tmp_path / "here")
    donor = _donor(tmp_path / "d", lanes=("check", "matrix"))
    (donor / "target" / "CACHEDIR.TAG").write_text("tag", encoding="utf-8")
    calls: list[str] = []

    def fake_copy(source: Path, destination: Path) -> None:
        calls.append(source.name)
        destination.mkdir(parents=True)

    out = seed(
        here,
        checkouts=[donor],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=fake_copy,
        volume_clones=_clones,
    )
    assert out == SeedOutcome("seeded", f"from {donor}")
    assert calls == ["debug", "check", "matrix"]
    assert (here / "target" / ".rustc_info.json").is_file()
    assert (here / "target" / "CACHEDIR.TAG").read_text(encoding="utf-8") == "tag"


def test_seed_leaves_out_a_lane_built_by_another_rustc_or_cargo_home(tmp_path: Path) -> None:
    """A stale clippy or matrix lane would only rebuild every dependency: leave it to Cargo."""
    here = _fresh(tmp_path / "here")
    donor = _donor(tmp_path / "d", lanes=("check",))
    _built(donor / "target" / "matrix", home=r"E:\packages\cargo")
    calls: list[str] = []

    def fake_copy(source: Path, destination: Path) -> None:
        calls.append(source.name)
        destination.mkdir(parents=True)

    out = seed(
        here,
        checkouts=[donor],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=fake_copy,
        volume_clones=_clones,
    )
    assert out == SeedOutcome("seeded", f"from {donor} (not its stale matrix)")
    assert calls == ["debug", "check"]


def test_seed_skips_built_target_and_non_cloning_volume(tmp_path: Path) -> None:
    here = _donor(tmp_path / "here")
    built = seed(
        here,
        checkouts=[],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=_never,
        volume_clones=_clones,
    )
    assert built == SeedOutcome("skipped", "target/ already built")
    fresh = _fresh(tmp_path / "fresh")
    out = seed(
        fresh,
        checkouts=[here],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=_never,
        volume_clones=lambda _: False,
    )
    assert out == SeedOutcome("skipped", "volume does not clone blocks")


def test_seed_failure_removes_partial_copy(tmp_path: Path) -> None:
    here = _fresh(tmp_path / "here")
    donor = _donor(tmp_path / "d", lanes=("check",))

    def flaky(source: Path, destination: Path) -> None:
        destination.mkdir(parents=True)
        if source.name == "check":
            raise OSError("robocopy exit 8")

    out = seed(
        here,
        checkouts=[donor],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=flaky,
        volume_clones=_clones,
    )
    assert out.status == "failed"
    assert "exit 8" in out.detail
    assert not (here / "target" / "debug").exists()
    assert not (here / "target" / "check").exists()
    assert not (here / "target" / ".seeding").exists()


def test_interrupted_seed_leaves_nothing_counted_as_built(tmp_path: Path) -> None:
    """A Ctrl-C mid-copy must not leave a directory that still holds the donor's member
    fingerprints, since the next init would then call target/ built and never repair it."""
    here = _fresh(tmp_path / "here")
    donor = _donor(tmp_path / "d", lanes=("check",))
    (donor / "target" / "debug" / ".fingerprint" / "stunt-core-0123456789abcdef").mkdir()

    def interrupted(source: Path, destination: Path) -> None:
        shutil.copytree(source, destination)
        if source.name == "check":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        seed(
            here,
            checkouts=[donor],
            rustc_vv=RUSTC,
            cargo_home=Path(HOME),
            copy=interrupted,
            volume_clones=_clones,
        )
    assert needs_seed(here / "target")
    assert not (here / "target" / ".seeding").exists()


def test_seed_clears_a_killed_seeds_staging(tmp_path: Path) -> None:
    """A killed process runs no cleanup; what it left in staging goes at the next seed."""
    here = _fresh(tmp_path / "here")
    stale = here / "target" / ".seeding" / "check" / ".fingerprint" / "stunt-core-0123456789abcdef"
    stale.mkdir(parents=True)
    out = seed(
        here,
        checkouts=[],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=_never,
        volume_clones=_clones,
    )
    assert out.status == "skipped"
    assert not (here / "target" / ".seeding").exists()


def test_failed_seed_names_what_it_could_not_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = _fresh(tmp_path / "here")
    donor = _donor(tmp_path / "d")

    def broken(_: Path, destination: Path) -> None:
        destination.mkdir(parents=True)
        raise OSError("robocopy exit 8")

    monkeypatch.setattr("stunt_reel.target_seed.shutil.rmtree", lambda *_a, **_k: None)
    out = seed(
        here,
        checkouts=[donor],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=broken,
        volume_clones=_clones,
    )
    assert out.status == "failed"
    assert out.detail == f"robocopy exit 8; could not remove {here / 'target' / '.seeding'}"


@pytest.mark.skipif(sys.platform != "win32", reason="Cargo's build locks are byte locks on Windows")
def test_seed_skips_a_donor_that_is_building(tmp_path: Path) -> None:
    here = _fresh(tmp_path / "here")
    donor = _donor(tmp_path / "d")
    held = _hold(donor / "target" / "debug" / ".cargo-lock")
    try:
        out = seed(
            here,
            checkouts=[donor],
            rustc_vv=RUSTC,
            cargo_home=Path(HOME),
            copy=_never,
            volume_clones=_clones,
        )
    finally:
        held.close()
    assert out == SeedOutcome("skipped", f"donor {donor} is building")


def _hold(lock: Path) -> BinaryIO:
    """Open and byte-lock *lock* the way a running Cargo build holds it; closing releases it."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(b"")
    handle = lock.open("r+b")
    # In a platform branch, so mypy analysing for Linux skips the Windows-only module.
    if sys.platform == "win32":
        import msvcrt  # noqa: PLC0415 - Windows-only module

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    return handle


@pytest.mark.skipif(sys.platform != "win32", reason="Cargo's build locks are byte locks on Windows")
def test_seed_skips_a_donor_whose_clippy_lane_is_building(tmp_path: Path) -> None:
    here = _fresh(tmp_path / "here")
    donor = _donor(tmp_path / "d")
    # The clippy and matrix lanes set CARGO_TARGET_DIR=target/<lane>, so their locks sit one
    # level down, under the lane's own debug/ profile.
    held = _hold(donor / "target" / "check" / "debug" / ".cargo-lock")
    try:
        out = seed(
            here,
            checkouts=[donor],
            rustc_vv=RUSTC,
            cargo_home=Path(HOME),
            copy=_never,
            volume_clones=_clones,
        )
    finally:
        held.close()
    assert out == SeedOutcome("skipped", f"donor {donor} is building")


@pytest.mark.skipif(sys.platform != "win32", reason="Cargo's build locks are byte locks on Windows")
def test_seed_falls_back_to_an_idle_donor(tmp_path: Path) -> None:
    here = _fresh(tmp_path / "here")
    busy = _donor(tmp_path / "busy", age=1)
    idle = _donor(tmp_path / "idle", age=600)
    held = _hold(busy / "target" / "debug" / ".cargo-lock")
    copied: list[Path] = []

    def fake_copy(source: Path, destination: Path) -> None:
        copied.append(source)
        destination.mkdir(parents=True)

    try:
        out = seed(
            here,
            checkouts=[busy, idle],
            rustc_vv=RUSTC,
            cargo_home=Path(HOME),
            copy=fake_copy,
            volume_clones=_clones,
        )
    finally:
        held.close()
    assert out == SeedOutcome("seeded", f"from {idle}")
    assert copied == [idle / "target" / "debug"]


@pytest.mark.skipif(sys.platform != "win32", reason="Cargo's build locks are byte locks on Windows")
def test_seed_passes_over_a_donor_whose_lock_cannot_be_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = _fresh(tmp_path / "here")
    shut = _donor(tmp_path / "shut", age=1)
    idle = _donor(tmp_path / "idle", age=600)
    lock = shut / "target" / "debug" / ".cargo-lock"
    lock.write_bytes(b"")
    real_open = Path.open

    def denied(path: Path, *args: object, **kwargs: object) -> object:
        if path == lock:
            raise PermissionError(13, "Access is denied", str(path))
        return real_open(path, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(Path, "open", denied)
    out = seed(
        here,
        checkouts=[shut, idle],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=lambda _s, destination: destination.mkdir(parents=True),
        volume_clones=_clones,
    )
    assert out == SeedOutcome("seeded", f"from {idle}")


def _workspace(root: Path, *members: str) -> None:
    """A Cargo workspace at *root* whose crates/* packages are named *members*."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "Cargo.toml").write_text(
        '[workspace]\nresolver = "3"\nmembers = [\n    "crates/*",\n]\n', encoding="utf-8"
    )
    for name in members:
        crate = root / "crates" / name.removeprefix("stunt-")
        crate.mkdir(parents=True)
        (crate / "Cargo.toml").write_text(f'[package]\nname = "{name}"\n', encoding="utf-8")
    (root / "crates" / "notes").mkdir(parents=True, exist_ok=True)


def test_workspace_members_reads_member_package_names(tmp_path: Path) -> None:
    _workspace(tmp_path, "stunt-core", "stunt-cli")
    assert workspace_members(tmp_path) == frozenset({"stunt-core", "stunt-cli"})
    with pytest.raises(FileNotFoundError):
        workspace_members(tmp_path / "missing")


def test_seed_skips_when_a_member_manifest_cannot_be_read(tmp_path: Path) -> None:
    """Without every member's name the seed could not drop their fingerprints: copy nothing."""
    here = _fresh(tmp_path / "here", "stunt-core", "stunt-cli")
    (here / "crates" / "cli" / "Cargo.toml").write_text("[package\n", encoding="utf-8")
    donor = _donor(tmp_path / "d")
    out = seed(
        here,
        checkouts=[donor],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=_never,
        volume_clones=_clones,
    )
    assert out.status == "skipped"
    assert out.detail.startswith("cannot read the workspace members:"), out.detail
    assert not (here / "target").exists()


def test_seed_skips_a_workspace_with_no_members(tmp_path: Path) -> None:
    here = tmp_path / "here"
    here.mkdir()
    (here / "Cargo.toml").write_text("[workspace]\nmembers = []\n", encoding="utf-8")
    out = seed(
        here,
        checkouts=[_donor(tmp_path / "d")],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=_never,
        volume_clones=_clones,
    )
    assert out == SeedOutcome("skipped", "cannot read the workspace members: none found")


def test_uses_cargo_home_keeps_escaped_spaces(tmp_path: Path) -> None:
    """rustc writes a space in a dep-info path as a backslash-space."""
    home = r"E:\my repo\.cache\cargo"
    a = _donor(tmp_path / "a", home=home)
    deps = a / "target" / "debug" / "deps"
    for dep_info in deps.glob("*.d"):
        dep_info.unlink()
    escaped = home.replace(" ", "\\ ") + r"\registry\src\index\serde\src\lib.rs"
    (deps / "serde-0123456789abcdef.d").write_text(f"{deps}\\x.d: {escaped}\n", encoding="utf-8")
    assert uses_cargo_home(a / "target", Path(home))
    assert not uses_cargo_home(a / "target", Path(r"E:\my"))


def test_seed_drops_workspace_fingerprints(tmp_path: Path) -> None:
    """Cargo trusts a workspace unit whose sources are older than its outputs, whatever they
    hold; a seed must never hand B the donor's build of B's own crates."""
    here = _fresh(tmp_path / "here", "stunt-core", "stunt-cli")
    donor = _donor(tmp_path / "d", lanes=("check", "matrix"))
    kept = ("serde-0123456789abcdef", "stunt-core-extra-0123456789abcdef")
    dropped = ("stunt-core-0123456789abcdef", "stunt-cli-fedcba9876543210")
    for profile in ("debug", "check/debug", "matrix/debug"):
        for name in (*kept, *dropped):
            (donor / "target" / profile / ".fingerprint" / name).mkdir(parents=True)

    def copy_tree(source: Path, destination: Path) -> None:
        shutil.copytree(source, destination)

    out = seed(
        here,
        checkouts=[donor],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=copy_tree,
        volume_clones=_clones,
    )
    assert out == SeedOutcome("seeded", f"from {donor}")
    for profile in ("debug", "check/debug", "matrix/debug"):
        seeded = here / "target" / profile / ".fingerprint"
        assert sorted(entry.name for entry in seeded.iterdir()) == sorted(kept), profile
        assert (donor / "target" / profile / ".fingerprint" / dropped[0]).is_dir()


def test_uses_cargo_home_reads_the_newest_dep_info(tmp_path: Path) -> None:
    """A donor once built with another cache keeps those .d files; its latest build decides."""
    a = _donor(tmp_path / "a")
    deps = a / "target" / "debug" / "deps"
    stale = deps / "aaa_old-0123456789abcdef.d"
    source = r"E:\packages\cargo\registry\src\x\lib.rs"
    stale.write_text(f"{stale}: {source}\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(stale, (old, old))
    assert uses_cargo_home(a / "target", Path(HOME))
    now = time.time() + 60
    os.utime(stale, (now, now))
    assert not uses_cargo_home(a / "target", Path(HOME))


@pytest.mark.skipif(sys.platform != "win32", reason="robocopy is Windows-only")
def test_robocopy_keeps_timestamps_and_raises_on_failure(tmp_path: Path) -> None:
    from stunt_reel.target_seed import robocopy  # noqa: PLC0415 - Windows-only helper

    source = tmp_path / "src"
    (source / "deps").mkdir(parents=True)
    unit = source / "deps" / "a.rlib"
    unit.write_bytes(b"x")
    stamp = 1_700_000_000_123_456_700
    os.utime(unit, ns=(stamp, stamp))
    robocopy(source, tmp_path / "dst")
    assert (tmp_path / "dst" / "deps" / "a.rlib").stat().st_mtime_ns == stamp
    with pytest.raises(OSError, match="exited"):
        robocopy(tmp_path / "absent", tmp_path / "dst2")


def test_seed_says_why_no_checkout_could_donate(tmp_path: Path) -> None:
    """One skip line per cause, so a check that rejects every donor shows which one."""
    here = _fresh(tmp_path / "here")
    others = [
        _donor(tmp_path / "r1", rustc="rustc 1.98.0\n"),
        _donor(tmp_path / "r2", rustc="rustc 1.98.0\n"),
        _donor(tmp_path / "h", home=r"E:\packages\cargo"),
        tmp_path / "unbuilt",
    ]
    expected = "no donor: 1 built against another cargo home, 2 built by another rustc, 1 not built"
    if sys.platform == "win32":
        drive = os.path.splitdrive(str(tmp_path))[0].upper()
        others.append(Path(("Y:" if drive == "Z:" else "Z:") + r"\elsewhere"))
        expected = expected.replace("not built", "not built, 1 on another drive")
    out = seed(
        here,
        checkouts=[here, *others],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=_never,
        volume_clones=_clones,
    )
    assert out == SeedOutcome("skipped", expected)
    alone = seed(
        here,
        checkouts=[here],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=_never,
        volume_clones=_clones,
    )
    assert alone == SeedOutcome("skipped", "no donor: no other checkout")


def test_workspace_members_follow_path_dependencies(tmp_path: Path) -> None:
    """Cargo trusts a path dependency's build by its sources' times too, listed member or not."""
    root = tmp_path / "ws"
    root.mkdir()
    (root / "Cargo.toml").write_text(
        '[package]\nname = "root"\n[workspace]\nmembers = ["crates/core"]\n'
        '[workspace.dependencies]\nshared = { path = "shared" }\n'
        '[patch.crates-io]\nserde = { path = "../vendor/serde" }\n',
        encoding="utf-8",
    )
    manifests = {
        "crates/core": '[package]\nname = "core"\n[dependencies]\nhelper = { path = "../helper" }\n'
        '[target."cfg(windows)".dev-dependencies]\nwin = { path = "../../win" }\n'
        'serde = "1"\n',
        "crates/helper": '[package]\nname = "helper"\n[dependencies]\ncore = { path = "../core" }\n',
        "shared": '[package]\nname = "shared"\n',
        "win": '[package]\nname = "win"\n',
        "../vendor/serde": '[package]\nname = "serde"\n',
    }
    for where, text in manifests.items():
        (root / where).mkdir(parents=True)
        (root / where / "Cargo.toml").write_text(text, encoding="utf-8")
    assert workspace_members(root) == frozenset(
        {"root", "core", "helper", "shared", "win", "serde"}
    )


def test_seed_passes_over_a_donor_rebuilt_after_it_was_ranked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A donor whose build changes rustc between ranking and locking is not copied."""
    here = _fresh(tmp_path / "here")
    first = _donor(tmp_path / "first", age=1)
    second = _donor(tmp_path / "second", age=600)
    locks_free = target_seed.build_locks_free

    @contextlib.contextmanager
    def rebuilt_first(target: Path) -> Iterator[bool]:
        if target == first / "target":
            _built(target, rustc="rustc 1.100.0")
        with locks_free(target) as free:
            yield free

    monkeypatch.setattr(target_seed, "build_locks_free", rebuilt_first)
    copied: list[Path] = []

    def fake_copy(source: Path, destination: Path) -> None:
        copied.append(source)
        destination.mkdir(parents=True)

    def run(checkouts: list[Path]) -> SeedOutcome:
        return seed(
            here,
            checkouts=checkouts,
            rustc_vv=RUSTC,
            cargo_home=Path(HOME),
            copy=fake_copy,
            volume_clones=_clones,
        )

    assert run([first]) == SeedOutcome("skipped", "no donor: 0 building, 1 rebuilt since ranked")
    _built(first / "target")
    assert run([first, second]) == SeedOutcome("seeded", f"from {second}")
    assert copied == [second / "target" / "debug"]


@pytest.mark.skipif(sys.platform != "win32", reason="Cargo's build locks are byte locks on Windows")
def test_seed_holds_the_donors_locks_while_it_copies(tmp_path: Path) -> None:
    """A donor build that starts mid-copy waits; once the seed is done it can lock again."""
    here = _fresh(tmp_path / "here")
    donor = _donor(tmp_path / "d", lanes=("check",))
    locks = [donor / "target" / "debug" / ".cargo-lock"]
    locks.append(donor / "target" / "check" / "debug" / ".cargo-build-lock")
    for lock in locks:
        lock.write_bytes(b"")
    during: list[bool] = []

    def probing_copy(_: Path, destination: Path) -> None:
        during.extend(_taken(lock) for lock in locks)
        destination.mkdir(parents=True)

    out = seed(
        here,
        checkouts=[donor],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=probing_copy,
        volume_clones=_clones,
    )
    assert out == SeedOutcome("seeded", f"from {donor}")
    assert during == [True] * 4
    assert not any(_taken(lock) for lock in locks)


def _taken(lock: Path) -> bool:
    """Whether another handle holds *lock*'s first byte, probed without changing the file."""
    with lock.open("r+b") as handle:
        if sys.platform == "win32":
            import msvcrt  # noqa: PLC0415 - Windows-only module

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    return False


def test_workspace_members_refuses_a_member_without_a_package(tmp_path: Path) -> None:
    _workspace(tmp_path, "stunt-core")
    (tmp_path / "crates" / "core" / "Cargo.toml").write_text("[lib]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="names no package"):
        workspace_members(tmp_path)


def test_workspace_members_refuses_members_that_are_not_a_list(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text('[workspace]\nmembers = "crates/*"\n', encoding="utf-8")
    with pytest.raises(TypeError, match="not a list"):
        workspace_members(tmp_path)


def test_clones_on_says_no_for_an_ntfs_or_non_windows_volume() -> None:
    """ReFS clones blocks; NTFS (every Windows system drive) and other platforms do not."""
    system = Path(os.environ.get("SYSTEMROOT", "/"))
    assert clones_on(system) is False
