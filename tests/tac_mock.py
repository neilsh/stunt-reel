"""Shared offline fixtures for the capture tests.

Provides a synthetic repository root with a staged-shaped film tree, a scripted film that
answers the generated Lua the way dosbox-automation would (trace and dump passes), and a
MAKEONE launcher whose guest returns to text mode on cue. No emulator starts.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from stunt_reel import dataroot
from stunt_reel.tac import luagen, playone
from stunt_reel.tac.automation import MockAutomation
from stunt_reel.tac.staging import ENGINE_FILES, MAKEONE_FILES

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from pathlib import Path

    from stunt_reel.tac.staging import StagedMount

__all__ = [
    "FILM_COLORS",
    "FakeFilm",
    "MakeOneState",
    "StagedRepo",
    "makeone_launcher",
    "staged_repo",
]

#: Distinct indices on a recorded film page.
FILM_COLORS: int = 40
_PAGE_BYTES = 320 * 200


class FakeFilm:
    """A film that answers the generated Lua: tick 0 for the dialog, then a moving clock, then a hold.

    The clock starts ``dialog_frames`` frames after the first traced frame and advances
    ``tick_step`` per emulated frame for ``moving_frames`` frames, then holds its last value
    with a static page (the end of the film). The global tick is the film tick plus 100.
    """

    def __init__(
        self,
        *,
        dialog_frames: int = 4,
        moving_frames: int = 40,
        tick_step: int = 2,
        flags: Mapping[int, int] | None = None,
        composed: bool = True,
    ):
        self.dialog_frames = dialog_frames
        self.moving_frames = moving_frames
        self.tick_step = tick_step
        #: Extra trace-mask bits (``luagen.TRACE_TORN``, ``TRACE_PALETTE``) by frame - first.
        self.flags = dict(flags or {})
        #: Whether an untorn page equals a composed page (False: the layout's offsets are wrong).
        self.composed = composed
        self.scripts: list[str] = []
        #: The first frame of the last clock pass; window passes count frames from it.
        self.first: int | None = None

    def tick(self, frame: int, first: int) -> int:
        moved = min(frame - first - self.dialog_frames + 1, self.moving_frames)
        return max(moved, 0) * self.tick_step

    def page(self, tick: int) -> bytes:
        return bytes((i * 7 + tick) % FILM_COLORS for i in range(_PAGE_BYTES))

    def _clock(self, lua: str, sampled: re.Match[str]) -> dict[str, Any]:
        first, last, every = (int(sampled.group(n)) for n in (1, 2, 3))
        self.first = first
        hold_match = re.search(r"hold >= (\d+)", lua)
        stop_match = re.search(r"or t >= (\d+)", lua)
        assert hold_match is not None
        ticks: list[int] = []
        last_tick, held = -1, 0
        for frame in range(first, last + 1, every):
            tick = self.tick(frame, first)
            ticks.append(tick)
            held = held + 1 if tick == last_tick else 0
            last_tick = tick
            stopped = stop_match is not None and tick >= int(stop_match.group(1))
            if tick > 0 and (held >= int(hold_match.group(1)) or stopped):
                break
        return {"done": True, "clock": "x" + ",".join(str(t) for t in ticks)}

    def _bits(self, frame: int) -> int:
        assert self.first is not None, "a window pass before any clock pass"
        return self.flags.get(frame - self.first, 0)

    def _windows(self, lua: str, listed: re.Match[str]) -> dict[str, Any]:
        assert self.first is not None, "a window pass before any clock pass"
        first = self.first
        starts = [int(x) for x in listed.group(1).split(",")]
        goals = [int(x) for x in listed.group(2).split(",")]
        span_match = re.search(r"for f = c, c \+ (\d+) do", lua)
        assert span_match is not None
        span = int(span_match.group(1)) + 1
        out: dict[str, Any] = {"done": True}
        entries: list[str] = []
        for start, goal in zip(starts, goals, strict=True):
            for frame in range(start, start + span):
                tick = self.tick(frame, first)
                changed = self.page(tick) != self.page(self.tick(frame - 1, first))
                step = bool(self._bits(frame) & luagen.TRACE_PALETTE)
                before = bool(self._bits(frame - 1) & luagen.TRACE_PALETTE)
                composed = self.composed and not self._bits(frame) & luagen.TRACE_TORN
                mask = (
                    int(changed)
                    + (luagen.TRACE_PALETTE if step else 0)
                    + (luagen.TRACE_COMPOSED if composed else luagen.TRACE_TORN)
                )
                entries.append(f"{frame}:{tick}:{tick + 100}:{mask}")
                if tick >= goal and changed and composed and not step and not before:
                    out[f"p{frame}"] = "x" + self.page(tick).hex()
                    out[f"c{frame}"] = "x" + (bytes([63, 0, 0]) * 256).hex()
                    break
        out["trace"] = "x" + ",".join(entries)
        return out

    def handler(self, lua: str) -> dict[str, Any]:
        self.scripts.append(lua)
        sampled = re.search(r"for f = (\d+), (\d+), (\d+) do", lua)
        if sampled is not None:
            return self._clock(lua, sampled)
        listed = re.search(r"local starts, goals = \{([^}]*)\}, \{([^}]*)\}", lua)
        if listed is not None:
            return self._windows(lua, listed)
        window = re.search(r"for f = (\d+), (\d+) do", lua)
        assert window is not None, "not a trace script"
        first, last = int(window.group(1)), int(window.group(2))
        hold = re.search(r"hold >= (\d+) then break", lua)
        dumps_match = re.search(r"local dumps = \{([^}]*)\}", lua)
        dumps = (
            [int(x) for x in dumps_match.group(1).split(",")]
            if dumps_match and dumps_match.group(1)
            else []
        )
        entries: list[str] = []
        out: dict[str, Any] = {"done": True}
        last_tick, held, previous = -1, 0, None
        for frame in range(first, last + 1):
            tick = self.tick(frame, first)
            held = held + 1 if tick == last_tick else 0
            last_tick = tick
            page = self.page(tick)
            mask = int(page != previous) | self.flags.get(frame - first, 0)
            entries.append(f"{tick}:{tick + 100}:{mask}")
            previous = page
            if frame in dumps:
                out[f"p{frame}"] = "x" + page.hex()
                out[f"c{frame}"] = "x" + (bytes([63, 0, 0]) * 256).hex()
                for n in range(1, len(re.findall(r'out\["m" \.\. f', lua)) + 1):
                    out[f"m{frame}_{n}"] = "x" + b"\x00".hex()
            if hold is not None and tick > 0 and held >= int(hold.group(1)):
                break
        out["trace"] = "x" + ",".join(entries)
        return out

    def runner(self) -> Callable[[], Any]:
        mock = MockAutomation(self.handler)

        @contextmanager
        def open_runner() -> Iterator[MockAutomation]:
            yield mock

        return open_runner


@dataclass(frozen=True)
class StagedRepo:
    """A synthetic checkout with a film tree and an output directory."""

    root: Path
    film: Path
    out: Path


@pytest.fixture
def staged_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[StagedRepo]:
    """Point the package at a temporary repository root with a synthetic film tree."""
    root = tmp_path / "stunt-reel"
    (root / ".git").mkdir(parents=True)
    corpus = root / "corpus" / "stisldem"
    vault = corpus / "VAULT"
    vault.mkdir(parents=True)
    for name in ENGINE_FILES:
        (corpus / name).write_bytes(b"engine")
    film = vault / "CTRY.FLM"
    film.write_bytes(b"FLM" + bytes(16))
    (vault / "CTRY.ALL").write_bytes(b"ALL")
    out = tmp_path / "out"

    monkeypatch.setattr(dataroot, "REPO_ROOT", root)
    # The synthetic PLAYONE.EXE matches no build's hash; read it as the unpatched one.
    monkeypatch.setattr(playone, "layout_for", lambda _exe: playone.UNPATCHED)
    dataroot.data_root.cache_clear()
    try:
        yield StagedRepo(root=root, film=film, out=out)
    finally:
        dataroot.data_root.cache_clear()


@pytest.fixture
def game_root(tmp_path: Path) -> Path:
    """A synthetic full-game tree: the MAKEONE files, a RES tree and files MAKEONE must not need."""
    root = tmp_path / "game"
    root.mkdir()
    for name in MAKEONE_FILES:
        (root / name).write_bytes(b"x" + name.encode())
    (root / "RES" / "sub").mkdir(parents=True)
    (root / "RES" / "a.bin").write_bytes(b"a")
    (root / "RES" / "sub" / "b.bin").write_bytes(b"b")
    (root / "VAULT").mkdir()
    (root / "VAULT" / "OTHER.FLM").write_bytes(b"o")
    (root / "VAULT" / "OTHER.TKE").write_bytes(b"t")
    (root / "SETS").mkdir()
    (root / "SETS" / "X.SET").write_bytes(b"s")
    return root


@dataclass
class MakeOneState:
    """What a scripted MAKEONE guest saw."""

    scripts: list[str] = field(default_factory=list)
    started: bool = False
    stopped: bool = False
    polls: int = 0
    #: Raised when the emulator is stopped, to model a failing teardown.
    stop_error: Exception | None = None
    #: The staged VAULT, set once a hung guest has written its archive.
    vault: Path | None = None


def makeone_launcher(
    *, text_after: int | None, archive: bytes | None
) -> tuple[Callable[[StagedMount], Any], MakeOneState]:
    """A MAKEONE guest: graphics until *text_after* polls, then text mode with *archive* written."""
    state = MakeOneState()

    class Client:
        def __init__(self, staged: StagedMount) -> None:
            self._staged = staged

        def run_script(self, text: str, *, timeout: float) -> dict[str, object]:  # noqa: ARG002
            state.scripts.append(text)
            return {"done": True}

        def is_text_mode(self) -> bool:
            state.polls += 1
            if text_after is None or state.polls <= text_after:
                if text_after is None and archive is not None and state.vault is None:
                    # A MAKEONE hang: the archive is written and the guest stays in graphics.
                    state.vault = self._staged.mount / "VAULT"
                    (state.vault / "CTRY.ALL").write_bytes(archive)
                return False
            if archive is not None:
                (self._staged.mount / "VAULT" / "CTRY.ALL").write_bytes(archive)
            return True

    @contextmanager
    def launch(staged: StagedMount) -> Iterator[Client]:
        state.started = True
        try:
            yield Client(staged)
        except BaseException:
            state.stopped = True  # a teardown error never outranks the one in flight
            raise
        state.stopped = True
        if state.stop_error is not None:
            raise state.stop_error

    return launch, state
