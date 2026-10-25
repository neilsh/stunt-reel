"""One capture session: stage the film, drive the emulator, sample and tear down.

run_session owns everything the two capture scripts used to duplicate: staging,
launch, the machine-wide port, accept and the PING, dialog settle, trap arming
through the transport operations, the callback lifetime, and teardown ordering.
The sample callback runs exactly once, on the calling thread, after the dialog
settles and the film is confirmed, and the session exists only inside it.

The callback gets a Session: next_frame() steps the free-running guest to its next
post-retrace trap hit and returns the Page stopped there. Page properties are lazy
and valid until the next next_frame() or session end; a page used later raises
StalePage.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from stunt_reel import dataroot
from stunt_reel.tac import playone, staging
from stunt_reel.tac.emulator import (
    EMULATOR_STOP_SECONDS,
    DosboxX,
    Emulator,
    EmulatorEvent,
    EmulatorUnavailable,
    GuestTimeout,
    PortTaken,
)
from stunt_reel.tac.transport import FRAME_BYTES, RGB, Transport

__all__ = [
    "BOOT_PAGES",
    "MAX_DIALOG_DUMPS",
    "SETTLED_DUMPS",
    "DialogSettled",
    "DialogUnsettled",
    "EmulatorUnavailable",
    "GuestTimeout",
    "Page",
    "PortTaken",
    "Session",
    "SessionError",
    "SessionEvent",
    "SessionLost",
    "ShortDump",
    "StalePage",
    "TrapTimeout",
    "run_session",
]

T = TypeVar("T")

#: Dumps allowed while waiting for the modal dialog to finish drawing.
MAX_DIALOG_DUMPS: int = 600
#: Consecutive identical dumps that count as a settled page.
SETTLED_DUMPS: int = 5
#: Distinct pages DOSBox-X and the game draw before the dialog appears.
BOOT_PAGES: int = 3


@dataclass(frozen=True)
class DialogSettled:
    """The LOAD FILM dialog stopped changing."""

    distinct_indices: int


#: Progress events the session reports to a caller that formats console output.
SessionEvent = EmulatorEvent | DialogSettled


class SessionError(RuntimeError):
    """A capture-session failure; emulator_status is set when the process had exited."""

    emulator_status: int | None = None


class DialogUnsettled(SessionError):  # noqa: N818 - the agreed interface name
    """The LOAD FILM dialog never stopped changing."""


class SessionLost(SessionError):  # noqa: N818 - the agreed interface name
    """The debugger connection died during the session."""


class ShortDump(SessionError):  # noqa: N818 - the agreed interface name
    """A framebuffer dump was not exactly one Mode 13h page."""


class StalePage(SessionError):  # noqa: N818 - the agreed interface name
    """A Page was used after the next frame or the end of the session."""


class TrapTimeout(SessionError):  # noqa: N818 - the agreed interface name
    """The guest did not reach the post-retrace trap in time."""


@contextlib.contextmanager
def _guest_errors(action: str) -> Iterator[None]:
    """Translate transport failures into the session's granular errors."""
    try:
        yield
    except TimeoutError as exc:
        raise GuestTimeout(f"the guest did not answer while {action}") from exc
    except ConnectionError as exc:
        raise SessionLost(f"lost the debugger while {action}: {exc}") from exc


def _require_frame(data: bytes) -> bytes:
    """Require exactly one Mode 13h page, raising ShortDump otherwise."""
    if len(data) != FRAME_BYTES:
        raise ShortDump(f"framebuffer dump was {len(data)} bytes, expected {FRAME_BYTES}")
    return data


def _resolve(path: Path, root: Path) -> Path:
    """Resolve a caller-supplied path against the repository root."""
    return path if path.is_absolute() else root / path


class Page:
    """One frame sampled while the guest is halted at the post-retrace trap.

    Properties are lazy: a probe that reads only film_clock never dumps the raster
    or the DAC. The page is valid until the next next_frame() or session end.
    """

    def __init__(self, transport: Transport, dgroup_segment: int) -> None:
        self._transport = transport
        self._dgroup_segment = dgroup_segment
        self._valid = True
        self._raster: bytes | None = None
        self._clock: tuple[int, int] | None = None
        self._palette: tuple[list[RGB], str] | None = None

    def _expire(self) -> None:
        self._valid = False

    def _require_valid(self) -> None:
        if not self._valid:
            raise StalePage("the page is valid only until the next frame or the session end")

    @property
    def raster(self) -> bytes:
        """The whole Mode 13h page, exactly 64,000 bytes."""
        self._require_valid()
        if self._raster is None:
            with _guest_errors("dumping the framebuffer"):
                self._raster = _require_frame(self._transport.dump_framebuffer())
        return self._raster

    @property
    def film_clock(self) -> tuple[int, int]:
        """The film clock and the global 50 Hz tick, read while the guest is halted."""
        self._require_valid()
        if self._clock is None:
            segment = self._dgroup_segment
            with _guest_errors("reading the film clock"):
                film_tick = self._read_word(segment, playone.FILM_CLOCK_OFFSET)
                global_tick = self._read_word(segment, playone.GLOBAL_TICK_OFFSET)
            self._clock = (film_tick, global_tick)
        return self._clock

    def _read_word(self, segment: int, offset: int) -> int:
        data = self._transport.read_memory((segment, offset), 2)
        if len(data) < 2:
            raise SessionLost(f"short read at {segment:04X}:{offset:04X}")
        return int.from_bytes(data, "little")

    @property
    def palette(self) -> tuple[list[RGB], str]:
        """The live DAC palette and its provenance (dacpal or fallback)."""
        self._require_valid()
        if self._palette is None:
            with _guest_errors("reading the DAC palette"):
                self._palette = self._transport.read_palette()
        return self._palette

    def read_memory(self, segment: int, offset: int, length: int) -> bytes:
        """Read real-mode memory while the guest is halted at this frame's trap."""
        self._require_valid()
        with _guest_errors(f"reading {segment:04X}:{offset:04X}"):
            return self._transport.read_memory((segment, offset), length)


class Session(Protocol):
    """What a sampler sees: the runtime DGROUP segment and one frame at a time."""

    dgroup_segment: int

    def next_frame(self) -> Page:
        """Run the guest to its next post-retrace trap hit and return the stopped page."""
        ...


class _LiveSession:
    """The session handed to a sampler; created and finished by run_session."""

    def __init__(self, transport: Transport, dgroup_segment: int) -> None:
        self._transport = transport
        self.dgroup_segment = dgroup_segment
        self._page: Page | None = None

    def next_frame(self) -> Page:
        """Stop the guest at its next post-retrace trap hit."""
        if self._page is not None:
            self._page._expire()
        try:
            self._transport.step_to_retrace()
        except TimeoutError as exc:
            raise TrapTimeout("the guest did not reach the post-retrace trap") from exc
        except ConnectionError as exc:
            raise SessionLost(f"lost the debugger while stepping to the trap: {exc}") from exc
        self._page = Page(self._transport, self.dgroup_segment)
        return self._page

    def finish(self) -> None:
        """Expire the last page so the sampler cannot use it after the session."""
        if self._page is not None:
            self._page._expire()
            self._page = None


def _settle(transport: Transport) -> int:
    """Dump the page until the modal dialog has finished drawing.

    No debugger command may touch the guest before this point: reads issued while
    PLAYONE.EXE unpacks kill it. Plain dumps of the framebuffer are safe, so the
    wait is driven entirely by repeated dumps. Returns the settled page's distinct
    palette index count.
    """
    with _guest_errors("waiting for the LOAD FILM dialog"):
        previous = _require_frame(transport.dump_framebuffer())
    equal = changes = 0
    for _ in range(MAX_DIALOG_DUMPS - 1):
        with _guest_errors("waiting for the LOAD FILM dialog"):
            raster = _require_frame(transport.dump_framebuffer())
        if raster == previous:
            equal += 1
        else:
            equal = 0
            changes += 1
        previous = raster
        if equal >= SETTLED_DUMPS and changes >= BOOT_PAGES:
            return len(set(raster))
    raise DialogUnsettled(
        f"LOAD FILM dialog never settled after {MAX_DIALOG_DUMPS} dumps "
        f"({len(set(previous))} indices on the last page)"
    )


def _attach_status(error: BaseException, status: int | None) -> None:
    """Carry the emulator's exit status on the propagating error for diagnostics."""
    if status is None:
        return
    try:
        error.emulator_status = status  # type: ignore[attr-defined]
    except AttributeError:
        return


def _teardown(transport: Transport | None, machine: Emulator) -> None:
    """Close the transport, release the port and stop the emulator; the first error wins."""
    errors: list[Exception] = []
    if transport is not None:
        try:
            transport.close()
        except Exception as exc:
            errors.append(exc)
    try:
        machine.stop(EMULATOR_STOP_SECONDS)
    except Exception as exc:
        errors.append(exc)
    if errors:
        raise errors[0]


def run_session(
    film: Path,
    out: Path,
    *,
    sample: Callable[[Session], T],
    conf: Path = Path("dosbox-parity.conf"),
    dgroup_segment: int = playone.DGROUP_RUNTIME_SEG,
    no_launch: bool = False,
    emulator: Emulator | None = None,
    progress: Callable[[SessionEvent], None] | None = None,
) -> T:
    """Run one capture session and return the sampler's result.

    The SOP 6 shared-write gate is applied to out once, before anything is staged or
    launched. The port is bound before the process launches; teardown closes the
    transport, releases the port and then stops the emulator, and a callback
    exception never masks it. progress, when given, receives typed events so a CLI
    can format its own output; the package never formats console text.
    """
    root = dataroot.REPO_ROOT
    film_path = _resolve(film, root)
    out_path = _resolve(out, root)
    conf_path = _resolve(conf, root)
    if dataroot.is_shared(out_path):
        dataroot.require_shared_write("the capture session")
    _stage, staged_conf = staging.stage_film(film_path, conf_path)
    machine: Emulator = (
        emulator
        if emulator is not None
        else DosboxX(staged_conf, no_launch=no_launch, progress=progress)
    )

    transport: Transport | None = None
    completed = False
    try:
        transport = machine.start()
        settled = _settle(transport)
        if progress is not None:
            progress(DialogSettled(settled))
        for key in playone.film_selection_keys(film_path.name):
            with _guest_errors("injecting a dialog keystroke"):
                transport.inject_key(key)
        session = _LiveSession(transport, dgroup_segment)
        try:
            result = sample(session)
        finally:
            session.finish()
        completed = True
        return result
    except BaseException as exc:
        status = machine.exit_status
        with contextlib.suppress(Exception):
            _teardown(transport, machine)
        _attach_status(exc, status)
        raise
    finally:
        if completed:
            _teardown(transport, machine)
