"""Seeding a new worktree's target/ from a donor checkout (ADR 0030)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import BinaryIO

import pytest

from stunt_reel.target_seed import (
    SeedOutcome,
    built_by,
    needs_seed,
    rank_donors,
    seed,
    uses_cargo_home,
    workspace_members,
)

RUSTC = "rustc 1.99.1 (58cf8f9c3 2026-10-13)\nhost: x86_64-pc-windows-msvc\n"
HOME = r"E:\git\stunt-reel\.cache\cargo"


def _donor(
    root: Path, *, rustc: str = RUSTC, home: str = HOME, lock: str = "a", age: float = 0
) -> Path:
    """A checkout whose target/ looks built by *rustc* against the registry under *home*."""
    target = root / "target"
    fingerprint = target / "debug" / ".fingerprint"
    deps = target / "debug" / "deps"
    fingerprint.mkdir(parents=True)
    deps.mkdir(parents=True)
    (root / "Cargo.lock").write_text(lock, encoding="utf-8")
    (target / ".rustc_info.json").write_text(
        json.dumps({"outputs": {"1": {"stdout": rustc}}}), encoding="utf-8"
    )
    source = home + r"\registry\src\index\serde_core\src\lib.rs"
    (deps / "serde_core-0123456789abcdef.d").write_text(
        f"{deps}\\serde_core-0123456789abcdef.d: {source}\n", encoding="utf-8"
    )
    stamp = time.time() - age
    os.utime(fingerprint, (stamp, stamp))
    return root


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
    donor = _donor(tmp_path / "d")
    for name in ("check", "matrix"):
        (donor / "target" / name).mkdir()
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
    donor = _donor(tmp_path / "d")
    (donor / "target" / "check").mkdir()

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
    donor = _donor(tmp_path / "d")
    (donor / "target" / "debug" / ".fingerprint" / "stunt-core-0123456789abcdef").mkdir()
    (donor / "target" / "check" / "debug").mkdir(parents=True)

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
    donor = _donor(tmp_path / "d")
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
