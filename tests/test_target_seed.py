"""Seeding a new worktree's target/ from a donor checkout (ADR 0030)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from stunt_reel.target_seed import (
    SeedOutcome,
    built_by,
    needs_seed,
    rank_donors,
    seed,
    uses_cargo_home,
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


def _fresh(root: Path) -> Path:
    root.mkdir()
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


@pytest.mark.skipif(sys.platform != "win32", reason="Cargo's build locks are byte locks on Windows")
def test_seed_skips_a_donor_that_is_building(tmp_path: Path) -> None:
    import msvcrt  # noqa: PLC0415 - Windows-only module

    here = _fresh(tmp_path / "here")
    donor = _donor(tmp_path / "d")
    lock = donor / "target" / "debug" / ".cargo-lock"
    lock.write_bytes(b"")
    with lock.open("r+b") as held:
        msvcrt.locking(held.fileno(), msvcrt.LK_NBLCK, 1)
        out = seed(
            here,
            checkouts=[donor],
            rustc_vv=RUSTC,
            cargo_home=Path(HOME),
            copy=_never,
            volume_clones=_clones,
        )
        held.seek(0)
        msvcrt.locking(held.fileno(), msvcrt.LK_UNLCK, 1)
    assert out == SeedOutcome("skipped", f"donor {donor} is building")
