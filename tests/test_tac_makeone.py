"""MAKEONE driven through the capture session: keys, the text-mode wait and the archive hand-back."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from archive_helpers import build_all
from stunt_reel import dataroot, parity_layout
from stunt_reel.tac import makeone
from stunt_reel.tac.bda import KEY_ENTER, char_to_key
from stunt_reel.tac.session import DialogSettled
from tac_mock import StagedRepo, makeone_guest

if TYPE_CHECKING:
    from pathlib import Path

ARCHIVE = build_all([b"one", b"two"])


class Modes:
    """A stand-in session whose video mode follows a script, then holds its last value."""

    def __init__(self, *modes: str) -> None:
        self._modes = list(modes)
        self.polls = 0

    def video_mode(self) -> str:
        self.polls += 1
        return self._modes[min(self.polls, len(self._modes)) - 1]


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
    assert makeone.film_selection_keys("BALLOON.FLM") == [char_to_key("b"), KEY_ENTER]


def test_text_mode_before_graphics_does_not_complete() -> None:
    clock = FakeClock()
    session = Modes("M_TEXT", "M_TEXT", "M_VGA", "M_TEXT")
    makeone.wait_for_text(session, timeout=60, poll=2, clock=clock, sleep=clock.sleep)  # type: ignore[arg-type]
    assert session.polls == 4


def test_the_timeout_fires() -> None:
    clock = FakeClock()
    with pytest.raises(makeone.MakeOneTimeout):
        makeone.wait_for_text(Modes("M_VGA"), timeout=10, poll=2, clock=clock, sleep=clock.sleep)  # type: ignore[arg-type]


def test_a_guest_that_never_leaves_text_mode_times_out() -> None:
    clock = FakeClock()
    with pytest.raises(makeone.MakeOneTimeout):
        makeone.wait_for_text(Modes("M_TEXT"), timeout=10, poll=2, clock=clock, sleep=clock.sleep)  # type: ignore[arg-type]


def test_make_all_returns_the_archive_written_into_the_mount(
    staged_repo: StagedRepo, game_root: Path, makeone_conf: Path
) -> None:
    emulator, keys = makeone_guest(text_after=2, archive=ARCHIVE)
    events: list[object] = []

    data = makeone.make_all(
        staged_repo.film,
        game_root=game_root,
        conf=makeone_conf,
        poll=0.0,
        emulator=emulator,
        progress=events.append,
    )

    assert data == ARCHIVE
    assert keys == makeone.film_selection_keys("CTRY.FLM")
    assert any(isinstance(event, DialogSettled) for event in events)
    assert emulator.stopped


def test_make_all_without_an_archive_raises(
    staged_repo: StagedRepo, game_root: Path, makeone_conf: Path
) -> None:
    emulator, _keys = makeone_guest(text_after=1, archive=None)
    with pytest.raises(makeone.NoArchive):
        makeone.make_all(
            staged_repo.film, game_root=game_root, conf=makeone_conf, poll=0.0, emulator=emulator
        )


def test_the_mount_is_gone_afterwards(
    staged_repo: StagedRepo, game_root: Path, makeone_conf: Path
) -> None:
    emulator, _keys = makeone_guest(text_after=1, archive=ARCHIVE)
    makeone.make_all(
        staged_repo.film, game_root=game_root, conf=makeone_conf, poll=0.0, emulator=emulator
    )
    assert _stage_dirs() == []

    emulator, _keys = makeone_guest(text_after=1, archive=None)
    with pytest.raises(makeone.NoArchive):
        makeone.make_all(
            staged_repo.film, game_root=game_root, conf=makeone_conf, poll=0.0, emulator=emulator
        )
    assert _stage_dirs() == []

    emulator, _keys = makeone_guest(text_after=None, archive=None)
    with pytest.raises(makeone.MakeOneTimeout):
        makeone.make_all(
            staged_repo.film,
            game_root=game_root,
            conf=makeone_conf,
            timeout=0.05,
            poll=0.01,
            emulator=emulator,
        )
    assert _stage_dirs() == []


def test_a_teardown_failure_after_a_good_run_keeps_the_archive(
    staged_repo: StagedRepo, game_root: Path, makeone_conf: Path
) -> None:
    emulator, _keys = makeone_guest(text_after=1, archive=ARCHIVE)

    def refuse_to_stop(_timeout: float) -> None:
        raise OSError("the emulator would not stop")

    emulator.stop = refuse_to_stop  # type: ignore[assignment]
    warnings: list[str] = []

    data = makeone.make_all(
        staged_repo.film,
        game_root=game_root,
        conf=makeone_conf,
        poll=0.0,
        emulator=emulator,
        warn=warnings.append,
    )

    assert data == ARCHIVE
    assert len(warnings) == 1
    assert "would not stop" in warnings[0]
    assert _stage_dirs() == []


def test_a_failure_before_the_archive_is_still_an_error(
    staged_repo: StagedRepo, game_root: Path, makeone_conf: Path
) -> None:
    emulator, _keys = makeone_guest(text_after=1, archive=None)
    emulator.stop = lambda _timeout: (_ for _ in ()).throw(OSError("late"))  # type: ignore[assignment]
    with pytest.raises(makeone.NoArchive):
        makeone.make_all(
            staged_repo.film,
            game_root=game_root,
            conf=makeone_conf,
            poll=0.0,
            emulator=emulator,
            warn=lambda _message: None,
        )
