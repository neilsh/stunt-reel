"""MAKEONE driven on dosbox-automation: keys, the text-mode wait and the archive hand-back."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from archive_helpers import build_all
from stunt_reel import dataroot, parity_layout
from stunt_reel.tac import automation, makeone, staging
from tac_mock import StagedRepo, makeone_launcher

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

ARCHIVE = build_all([b"one", b"two"])


def test_makeone_launches_with_the_archive_cpu_profile(
    staged_repo: StagedRepo, game_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MAKEONE is not sampled, so it runs on the fast core (13 s against 179 s, ADR 0023)."""
    confs: list[list[str]] = []

    def fake_launched(write_conf: Callable[[int], Path]) -> object:
        confs.append(write_conf(1).read_text(encoding="utf-8").splitlines())
        return object()

    monkeypatch.setattr(automation, "launched", fake_launched)
    staged = staging.stage_makeone(staged_repo.film, game_root)

    makeone._launch(staged)

    assert "cpu_cycles = max" in confs[0]
    assert confs[0][-1] == "makeone.exe"


class Modes:
    """A stand-in client whose text-mode flag follows a script, then holds its last value."""

    def __init__(self, *modes: bool) -> None:
        self._modes = list(modes)
        self.polls = 0

    def is_text_mode(self) -> bool:
        self.polls += 1
        return self._modes[min(self.polls, len(self._modes)) - 1]

    def run_script(self, text: str, *, timeout: float) -> dict[str, object]:  # noqa: ARG002
        raise AssertionError("not used")


class FakeClock:
    """A clock that sleeping advances, so timeout tests do not wait."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _stage_dirs() -> list[str]:
    root = dataroot.data_root() / parity_layout.stage_root()
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


def test_keys_are_the_letter_then_enter() -> None:
    assert makeone.film_selection_names("BALLOON.FLM") == ["KBD_b", "KBD_enter"]


def test_text_mode_before_graphics_does_not_complete() -> None:
    clock = FakeClock()
    client = Modes(True, True, False, True)
    makeone.wait_for_text(client, timeout=60, poll=2, clock=clock, sleep=clock.sleep)
    assert client.polls == 4


def test_the_timeout_fires() -> None:
    clock = FakeClock()
    with pytest.raises(makeone.MakeOneTimeout):
        makeone.wait_for_text(Modes(False), timeout=10, poll=2, clock=clock, sleep=clock.sleep)


def test_a_guest_that_never_leaves_text_mode_times_out() -> None:
    clock = FakeClock()
    with pytest.raises(makeone.MakeOneTimeout):
        makeone.wait_for_text(Modes(True), timeout=10, poll=2, clock=clock, sleep=clock.sleep)


def test_make_all_returns_the_archive_written_into_the_mount(
    staged_repo: StagedRepo, game_root: Path
) -> None:
    launch, state = makeone_launcher(text_after=2, archive=ARCHIVE)
    lines: list[str] = []

    data = makeone.make_all(
        staged_repo.film, game_root=game_root, poll=0.0, launch=launch, progress=lines.append
    )

    assert data == ARCHIVE
    assert '{"KBD_c", "KBD_enter"}' in state.scripts[0]
    assert any("requester" in line for line in lines)
    assert state.stopped


def test_make_all_without_an_archive_raises(staged_repo: StagedRepo, game_root: Path) -> None:
    launch, _state = makeone_launcher(text_after=1, archive=None)
    with pytest.raises(makeone.NoArchive):
        makeone.make_all(staged_repo.film, game_root=game_root, poll=0.0, launch=launch)


def test_the_mount_is_gone_afterwards(staged_repo: StagedRepo, game_root: Path) -> None:
    launch, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    makeone.make_all(staged_repo.film, game_root=game_root, poll=0.0, launch=launch)
    assert _stage_dirs() == []

    launch, _state = makeone_launcher(text_after=1, archive=None)
    with pytest.raises(makeone.NoArchive):
        makeone.make_all(staged_repo.film, game_root=game_root, poll=0.0, launch=launch)
    assert _stage_dirs() == []

    launch, _state = makeone_launcher(text_after=None, archive=None)
    with pytest.raises(makeone.MakeOneTimeout):
        makeone.make_all(
            staged_repo.film, game_root=game_root, timeout=0.05, poll=0.01, launch=launch
        )
    assert _stage_dirs() == []


def test_a_teardown_failure_after_a_good_run_keeps_the_archive(
    staged_repo: StagedRepo, game_root: Path
) -> None:
    launch, state = makeone_launcher(text_after=1, archive=ARCHIVE)
    state.stop_error = OSError("the emulator would not stop")
    warnings: list[str] = []

    data = makeone.make_all(
        staged_repo.film, game_root=game_root, poll=0.0, launch=launch, warn=warnings.append
    )

    assert data == ARCHIVE
    assert len(warnings) == 1
    assert "would not stop" in warnings[0]
    assert _stage_dirs() == []


def test_a_failure_before_the_archive_is_still_an_error(
    staged_repo: StagedRepo, game_root: Path
) -> None:
    launch, state = makeone_launcher(text_after=1, archive=None)
    state.stop_error = OSError("late")
    with pytest.raises(makeone.NoArchive):
        makeone.make_all(
            staged_repo.film, game_root=game_root, poll=0.0, launch=launch, warn=lambda _m: None
        )
