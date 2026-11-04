"""``init`` and ``mise run seed`` print one line about seeding target/, and never fail on it."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel.dataroot import cache_root
from stunt_reel.target_seed import SeedOutcome

if TYPE_CHECKING:
    import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import worktree_init  # noqa: E402


def test_seed_line_formats_each_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: "rustc 1.99.1\n")
    monkeypatch.setattr(worktree_init, "_worktrees", lambda _repo: [])
    for outcome, line in [
        (SeedOutcome("seeded", r"from E:\a"), r"  + target/ seeded from E:\a"),
        (
            SeedOutcome("skipped", "volume does not clone blocks"),
            "  - target/ not seeded: volume does not clone blocks",
        ),
        (SeedOutcome("failed", "robocopy exit 8"), "  ! seed: robocopy exit 8"),
    ]:
        monkeypatch.setattr(worktree_init, "seed", lambda *_args, o=outcome, **_kwargs: o)
        assert worktree_init._seed_target() == line


def test_seed_line_without_rustc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: None)
    assert worktree_init._seed_target() == "  - target/ not seeded: rustc not on PATH"


def test_seed_line_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_repo: Path) -> list[object]:
        raise RuntimeError("git missing")

    monkeypatch.setattr(worktree_init, "_worktrees", boom)
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: "rustc 1.99.1\n")
    assert worktree_init._seed_target() == "  ! seed: RuntimeError: git missing"


def test_seed_command_is_wired(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(worktree_init, "_seed_target", lambda: "  - target/ not seeded: x")
    assert worktree_init.main(["seed"]) == 0
    assert "not seeded: x" in capsys.readouterr().out


def test_seed_uses_the_cargo_home_mise_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Python must judge donors by the very path mise hands cargo, not a second derivation."""
    seen: list[Path] = []

    def fake_seed(*_args: object, cargo_home: Path, **_kwargs: object) -> SeedOutcome:
        seen.append(cargo_home)
        return SeedOutcome("skipped", "x")

    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: "rustc 1.99.1\n")
    monkeypatch.setattr(worktree_init, "_worktrees", lambda _repo: [])
    monkeypatch.setattr(worktree_init, "seed", fake_seed)
    monkeypatch.setenv("STUNT_CARGO_HOME", str(tmp_path / "home"))
    worktree_init._seed_target()
    assert seen == [tmp_path / "home"]


def test_seed_command_fails_when_the_seed_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """init carries on after a failed seed; ``mise run seed`` on its own reports it by status."""
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: "rustc 1.99.1\n")
    monkeypatch.setattr(worktree_init, "_worktrees", lambda _repo: [])
    for outcome, status in [
        (SeedOutcome("failed", "robocopy exit 8"), 1),
        (SeedOutcome("skipped", "volume does not clone blocks"), 0),
        (SeedOutcome("seeded", "from E:/a"), 0),
    ]:
        monkeypatch.setattr(worktree_init, "seed", lambda *_args, o=outcome, **_kwargs: o)
        assert worktree_init.main(["seed"]) == status, outcome
    assert "! seed: robocopy exit 8" in capsys.readouterr().out


def test_seed_warns_when_the_cargo_home_is_not_the_shared_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """mise's fallback names the cache through this checkout's link: same files, other path."""
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: None)
    shared = cache_root() / "cargo"
    monkeypatch.setenv("STUNT_CARGO_HOME", str(shared).replace("\\", "/"))
    assert worktree_init._seed_target() == "  - target/ not seeded: rustc not on PATH"
    monkeypatch.setenv("STUNT_CARGO_HOME", str(tmp_path / ".cache" / "cargo"))
    lines = worktree_init._seed_target().splitlines()
    assert lines[1] == (
        f"  ! CARGO_HOME {tmp_path / '.cache' / 'cargo'} is not {shared}: "
        "every dependency rebuilds here"
    )


def test_concurrent_ensures_seed_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate starts four cargo lanes at once; only the first seeds, the rest find it built."""
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(worktree_init, "ensure_hooks_path", lambda _repo: [])
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: "rustc 1.99.1\n")
    monkeypatch.setattr(worktree_init, "_worktrees", lambda _repo: [])
    calls: list[Path] = []

    def slow_seed(checkout: Path, **_kwargs: object) -> SeedOutcome:
        calls.append(checkout)
        time.sleep(0.2)
        (checkout / "target" / "debug").mkdir(parents=True)
        return SeedOutcome("seeded", "from elsewhere")

    monkeypatch.setattr(worktree_init, "seed", slow_seed)
    threads = [threading.Thread(target=worktree_init._ensure) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert calls == [tmp_path]


def test_ensure_is_quiet_when_nothing_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A built target/ and a set hooks path cost a few stats and print nothing."""
    (tmp_path / "target" / "debug").mkdir(parents=True)
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        worktree_init, "ensure_hooks_path", lambda _repo: ["  = core.hooksPath .githooks"]
    )

    def no_seed() -> str:
        raise AssertionError("a built target/ is never seeded")

    monkeypatch.setattr(worktree_init, "_seed_target", no_seed)
    assert worktree_init._ensure() == 0
    assert capsys.readouterr().out == ""


def test_ensure_reports_what_it_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        worktree_init, "ensure_hooks_path", lambda _repo: ["  + core.hooksPath -> .githooks"]
    )
    monkeypatch.setattr(worktree_init, "_seed_target", lambda: "  + target/ seeded from E:\a")
    assert worktree_init.main(["ensure"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "  + core.hooksPath -> .githooks",
        "  + target/ seeded from E:\a",
    ]
