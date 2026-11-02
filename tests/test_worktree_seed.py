"""``init`` and ``mise run seed`` print one line about seeding target/, and never fail on it."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

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
    assert worktree_init._seed_target() == "  ! seed: git missing"


def test_seed_command_is_wired(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(worktree_init, "_seed_target", lambda: "  - target/ not seeded: x")
    assert worktree_init.main(["seed"]) == 0
    assert "not seeded: x" in capsys.readouterr().out
