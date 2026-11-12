"""MAKEONE driven on dosbox-automation: keys, the text-mode wait and the archive hand-back."""

from __future__ import annotations

import os
import zlib
from typing import TYPE_CHECKING

import pytest

from archive_helpers import build_all
from stunt_reel import dataroot, parity_layout
from stunt_reel.tac import automation, makeone, staging, timeout_evidence
from tac_mock import SCREEN, StagedRepo, makeone_launcher

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
    assert makeone.film_requester_names("BALLOON.FLM") == ["KBD_b", "KBD_enter"]


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


def _hang(
    staged_repo: StagedRepo,
    game_root: Path,
    archive: bytes | None,
    *,
    change: bool = False,
    touch: bool = False,
    warnings: list[str] | None = None,
    hangs: list[bool] | None = None,
    text_after: int | None = None,
    evidence_dir: Path | None = None,
) -> bytes:
    """A run whose guest stays in graphics past *timeout*; *change* keeps rewriting the archive.

    *text_after* returns the guest to text mode after that many polls instead of never.
    """
    launch, state = makeone_launcher(text_after=text_after, archive=archive, early_archive=True)
    clock = FakeClock()

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if change and state.vault is not None:
            with (state.vault / "CTRY.ALL").open("ab") as out:
                out.write(b"x")
        if touch and state.vault is not None:
            path = state.vault / "CTRY.ALL"
            stamp = path.stat().st_mtime_ns + 1_000_000_000
            os.utime(path, ns=(stamp, stamp))

    return makeone.make_all(
        staged_repo.film,
        game_root=game_root,
        timeout=10,
        poll=2,
        stable=60,
        launch=launch,
        clock=clock,
        sleep=sleep,
        warn=(warnings if warnings is not None else []).append,
        on_hang=lambda: (hangs if hangs is not None else []).append(True),
        evidence_dir=evidence_dir,
    )


def test_a_makeone_hang_with_a_stable_archive_is_accepted(
    staged_repo: StagedRepo, game_root: Path
) -> None:
    warnings: list[str] = []
    hangs: list[bool] = []

    data = _hang(staged_repo, game_root, ARCHIVE, warnings=warnings, hangs=hangs)

    assert data == ARCHIVE
    assert hangs == [True]
    assert len(warnings) == 1
    assert "MAKEONE hang" in warnings[0]
    assert _stage_dirs() == []


def test_a_timeout_saves_the_guest_screen_and_lists_the_emulators(
    staged_repo: StagedRepo,
    game_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        timeout_evidence, "emulator_processes", lambda: ["101 dosbox.exe", "202 dosbox-x.exe"]
    )
    warnings: list[str] = []

    _hang(staged_repo, game_root, ARCHIVE, warnings=warnings, evidence_dir=tmp_path / "shots")

    (picture,) = (tmp_path / "shots").glob("CTRY-*.png")
    assert any(f"saved as {picture}" in line for line in warnings)
    assert any("101 dosbox.exe; 202 dosbox-x.exe" in line for line in warnings)
    data = picture.read_bytes()
    assert data.startswith(b"\x89PNG")
    # The pixels are the guest's page, row for row.
    idat = data.index(b"IDAT") + 4
    rows = zlib.decompress(data[idat : data.index(b"IEND") - 8])
    assert b"".join(rows[1 + y * 321 : 321 + y * 321] for y in range(200)) == SCREEN


def test_a_failed_screen_grab_is_logged_and_the_run_still_ends_normally(
    staged_repo: StagedRepo,
    game_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> list[str]:
        raise OSError("no tasklist")

    monkeypatch.setattr(timeout_evidence, "emulator_processes", broken)
    monkeypatch.setattr(timeout_evidence, "screen_script", lambda: "-- no page")
    warnings: list[str] = []

    data = _hang(staged_repo, game_root, ARCHIVE, warnings=warnings, evidence_dir=tmp_path)

    assert data == ARCHIVE
    assert any("no screen picture" in line for line in warnings)
    assert any("no process list" in line for line in warnings)
    assert list(tmp_path.glob("*.png")) == []


def test_a_return_to_dos_during_the_stability_wait_is_not_a_hang(
    staged_repo: StagedRepo, game_root: Path
) -> None:
    warnings: list[str] = []
    hangs: list[bool] = []

    # wait_for_text polls 7 times before its 10 s timeout; the 8th poll, after the
    # stability wait, finds the guest back in text mode.
    data = _hang(staged_repo, game_root, ARCHIVE, warnings=warnings, hangs=hangs, text_after=7)

    assert data == ARCHIVE
    assert hangs == []
    assert warnings == []


def test_a_makeone_hang_with_a_changing_archive_is_refused(
    staged_repo: StagedRepo, game_root: Path
) -> None:
    hangs: list[bool] = []
    with pytest.raises(makeone.MakeOneTimeout, match="still changing"):
        _hang(staged_repo, game_root, ARCHIVE, change=True, hangs=hangs)
    assert hangs == []
    assert _stage_dirs() == []


def test_a_makeone_hang_with_no_archive_is_refused(
    staged_repo: StagedRepo, game_root: Path
) -> None:
    with pytest.raises(makeone.MakeOneTimeout, match="no archive was written"):
        _hang(staged_repo, game_root, None)


def test_a_makeone_hang_with_an_empty_archive_is_refused(
    staged_repo: StagedRepo, game_root: Path
) -> None:
    with pytest.raises(makeone.MakeOneTimeout, match="archive is empty"):
        _hang(staged_repo, game_root, b"")


def test_a_makeone_hang_whose_mtime_alone_changes_is_refused(
    staged_repo: StagedRepo, game_root: Path
) -> None:
    with pytest.raises(makeone.MakeOneTimeout, match="still changing"):
        _hang(staged_repo, game_root, ARCHIVE, touch=True)


def test_the_process_list_is_a_list_of_pid_name_lines() -> None:
    assert all(" " in line for line in timeout_evidence.emulator_processes())


def test_a_page_png_refuses_a_page_of_the_wrong_size() -> None:
    with pytest.raises(ValueError, match="64000"):
        timeout_evidence.page_png(b"short")


def test_two_timeouts_of_one_film_keep_two_pictures(
    staged_repo: StagedRepo, game_root: Path, tmp_path: Path
) -> None:
    for _ in range(2):
        _hang(staged_repo, game_root, ARCHIVE, evidence_dir=tmp_path)

    assert len(list(tmp_path.glob("CTRY-*.png"))) == 2


def test_a_timeout_saves_the_picture_without_a_warn_callback(
    staged_repo: StagedRepo, game_root: Path, tmp_path: Path
) -> None:
    launch, _state = makeone_launcher(text_after=None, archive=ARCHIVE, early_archive=True)
    clock = FakeClock()

    makeone.make_all(
        staged_repo.film,
        game_root=game_root,
        timeout=10,
        poll=2,
        stable=60,
        launch=launch,
        clock=clock,
        sleep=clock.sleep,
        evidence_dir=tmp_path,
    )

    assert len(list(tmp_path.glob("CTRY-*.png"))) == 1
